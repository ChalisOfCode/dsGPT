use serde_json::Value;
use std::path::PathBuf;
use std::sync::{Mutex, Arc, atomic::{AtomicBool, Ordering}};
use tauri::State;

#[derive(Default)]
pub struct HistorySelection(pub Mutex<Option<(PathBuf, String)>>, Arc<AtomicBool>);
struct Busy(Arc<AtomicBool>);
impl Drop for Busy { fn drop(&mut self) { self.0.store(false, Ordering::Release); } }
fn acquire(selection: &HistorySelection) -> Result<Busy, String> {
    selection.1.compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| "Another local import operation is active")?;
    Ok(Busy(selection.1.clone()))
}

fn managed_python() -> Result<PathBuf, String> {
    if !cfg!(windows) { return Err("Local archive import requires the managed Windows app".into()); }
    let exe = std::env::current_exe().map_err(|_| "Cannot locate the installed app")?;
    let root = exe.parent().and_then(|p| p.parent()).ok_or("Cannot locate managed installation")?;
    let python = root.join("python").join("python.exe");
    if !python.is_file() { return Err("Install the managed desktop package to import local archives".into()); }
    Ok(python)
}

fn command(python: &PathBuf, module: &str, args: &[&std::ffi::OsStr]) -> Result<Value, String> {
    let mut process = std::process::Command::new(python);
    process.args(["-I", "-m", module]).args(args).stdin(std::process::Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        process.creation_flags(0x08000000);
    }
    let output = process.output().map_err(|_| "Local backend command could not start")?;
    if output.stdout.len() > 4 * 1024 * 1024 || output.stderr.len() > 16384 {
        return Err("Local import response exceeded its display limit".into());
    }
    if !output.status.success() {
        let error = serde_json::from_slice::<Value>(&output.stderr).ok()
            .and_then(|v| v.get("error").and_then(Value::as_str).map(str::to_owned));
        return Err(error.unwrap_or_else(|| "Local import operation failed. Review the backend state before retrying.".into()));
    }
    if output.stdout.is_empty() { return Ok(Value::Null); }
    serde_json::from_slice(&output.stdout).map_err(|_| "Invalid local backend response".into())
}

async fn require_local_owner(session: &State<'_, super::Session>) -> Result<(), String> {
    let c = session.0.lock().map_err(|_| "Session unavailable")?.clone().ok_or("Connect first")?;
    if c.origin != "http://127.0.0.1:18765" { return Err("Connect to this PC's managed backend before importing".into()); }
    let response = super::http()?.get(format!("{}/v1/capabilities", c.origin)).bearer_auth(c.token)
        .send().await.map_err(|_| "Local backend unavailable")?;
    if !response.status().is_success() { return Err("Local owner connection required".into()); }
    let cap: Value = response.json().await.map_err(|_| "Invalid capability response")?;
    if cap["permissions"]["search_administration"] != true { return Err("Only the local owner may import archives".into()); }
    Ok(())
}

#[tauri::command]
pub async fn preview_history_import(session: State<'_, super::Session>, selection: State<'_, HistorySelection>) -> Result<Option<Value>, String> {
    let _busy = acquire(&selection)?;
    require_local_owner(&session).await?;
    let python = managed_python()?;
    let Some(file) = rfd::AsyncFileDialog::new().set_title("Choose a local ChatGPT export")
        .add_filter("ChatGPT archive", &["zip", "json"]).pick_file().await else { return Ok(None); };
    let path = file.path().to_path_buf();
    let chosen = path.clone();
    let preview = tauri::async_runtime::spawn_blocking(move || { let _operation = _busy; command(&python, "dsgpt.history_import", &[
        "preview".as_ref(), "--file".as_ref(), chosen.as_os_str(),
    ]) }).await.map_err(|_| "Local preview interrupted")??;
    let sha = preview["archive_sha256"].as_str().ok_or("Invalid archive preview")?.to_owned();
    *selection.0.lock().map_err(|_| "Import selection unavailable")? = Some((path, sha));
    Ok(Some(preview))
}

#[tauri::command]
pub async fn apply_history_import(sha256: String, request_id: String, confirm_restart: bool,
    session: State<'_, super::Session>, selection: State<'_, HistorySelection>) -> Result<Value, String> {
    let _busy = acquire(&selection)?;
    require_local_owner(&session).await?;
    if !confirm_restart || sha256.len() != 64 || !sha256.bytes().all(|c| c.is_ascii_hexdigit())
        || request_id.len() != 36 || !request_id.chars().enumerate().all(|(i,c)| if [8,13,18,23].contains(&i) { c == '-' } else { c.is_ascii_hexdigit() }) {
        return Err("Review the archive preview and confirm the backend restart".into());
    }
    let (path, expected) = selection.0.lock().map_err(|_| "Import selection unavailable")?.clone().ok_or("Preview an archive first")?;
    if expected != sha256 { return Err("Archive selection changed; preview again".into()); }
    let python = managed_python()?;
    let data = PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or("Windows profile unavailable")?).join("dsGPT/managed/data");
    tauri::async_runtime::spawn_blocking(move || {
        let _operation = _busy;
        command(&python, "dsgpt.managed", &["stop".as_ref()])?;
        let result = command(&python, "dsgpt.history_import", &[
            "apply".as_ref(), "--file".as_ref(), path.as_os_str(), "--data-dir".as_ref(), data.as_os_str(),
            "--sha256".as_ref(), sha256.as_ref(), "--request-id".as_ref(), request_id.as_ref(),
        ]);
        let restarted = command(&python, "dsgpt.managed", &["start".as_ref()]);
        if restarted.is_err() { return Err("Backend restart failed. Import may have committed; reopen the managed app and review imports before retrying.".into()); }
        result
    }).await.map_err(|_| "Local import interrupted; review imports before retrying")?
}
