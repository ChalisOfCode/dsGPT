use crate::{http, Session};
use serde::{Deserialize, Serialize};
use std::{path::PathBuf, process::{Child, Command, Stdio}, sync::Mutex, time::{SystemTime, UNIX_EPOCH}};
use tauri::State;

#[derive(Default)]
pub struct PhoneSetup(Mutex<Option<Child>>);

#[derive(Clone, Serialize, Deserialize)]
pub struct Progress {
    status: String,
    phase: String,
    message: String,
    updated: u64,
}
fn now() -> u64 { SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs() }
fn progress(status: &str, message: &str) -> Progress {
    Progress { status: status.into(), phase: "desktop".into(), message: message.into(), updated: now() }
}
fn path() -> Result<PathBuf, String> {
    Ok(PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or("Automatic connection requires the installed Windows app")?)
        .join("dsGPT/managed/data/phone-setup.json"))
}
fn read() -> Result<Progress, String> {
    let path = path()?;
    if !path.exists() { return Ok(progress("idle", "Connect your Pixel automatically using its existing wireless debugging connection.")); }
    if std::fs::metadata(&path).map_err(|_| "Cannot inspect phone status")?.len() > 4096 { return Err("Invalid phone setup status".into()); }
    let mut value: Progress = serde_json::from_slice(&std::fs::read(path).map_err(|_| "Cannot read phone status")?)
        .map_err(|_| "Cannot read phone setup progress")?;
    if !["idle", "running", "succeeded", "paired", "needs_attention"].contains(&value.status.as_str()) || value.message.len() > 2400 {
        return Err("Invalid phone setup status".into());
    }
    if value.status == "running" && now().saturating_sub(value.updated) > 600 {
        value = progress("needs_attention", "The last connection attempt was interrupted. Retry automatic connection.");
    }
    Ok(value)
}

#[tauri::command]
pub fn phone_setup_status(job: State<'_, PhoneSetup>) -> Result<Progress, String> {
    let mut value = read()?;
    let mut child = job.0.lock().map_err(|_| "Phone setup unavailable")?;
    if let Some(process) = child.as_mut() {
        if process.try_wait().map_err(|_| "Cannot inspect phone setup")?.is_some() {
            *child = None;
            if value.status == "running" {
                value = progress("needs_attention", "Connection stopped before it was verified. Retry automatic connection.");
                if let Ok(target) = path() { let _ = std::fs::write(target, serde_json::to_vec(&value).unwrap_or_default()); }
            }
        }
    }
    Ok(value)
}

#[tauri::command]
pub async fn start_phone_setup(session: State<'_, Session>, job: State<'_, PhoneSetup>) -> Result<Progress, String> {
    if !cfg!(windows) || std::env::var_os("DSGPT_ACCEPTANCE_RUN_ID").is_some() {
        return Err("Automatic phone connection requires the installed Windows app".into());
    }
    let connection = session.0.lock().map_err(|_| "Session unavailable")?.clone().ok_or("Connect the desktop first")?;
    if connection.origin != "http://127.0.0.1:18765" {
        return Err("Open dsGPT on the PC that runs your local models to connect this Pixel".into());
    }
    let response = http()?.get(format!("{}/v1/device", connection.origin)).bearer_auth(&connection.token)
        .send().await.map_err(|_| "Desktop connection unavailable")?;
    if !response.status().is_success() { return Err("Reconnect the desktop owner before pairing".into()); }
    let identity: serde_json::Value = response.json().await.map_err(|_| "Cannot verify desktop owner")?;
    if !identity["scopes"].as_array().is_some_and(|scopes| scopes.iter().any(|s| s == "admin")) {
        return Err("Only the desktop owner can connect a Pixel".into());
    }
    let mut child = job.0.lock().map_err(|_| "Phone setup unavailable")?;
    if let Some(process) = child.as_mut() {
        if process.try_wait().map_err(|_| "Cannot inspect phone setup")?.is_none() { return read(); }
        *child = None;
    }
    let previous = read()?;
    if previous.status == "running" { return Ok(previous); }
    let executable = std::env::current_exe().map_err(|_| "Installed app path unavailable")?;
    let root = executable.parent().and_then(|p| p.parent()).ok_or("Installed app path unavailable")?;
    let manifest: serde_json::Value = serde_json::from_slice(&std::fs::read(root.join("application-manifest.json"))
        .map_err(|_| "Install the complete dsGPT update first")?).map_err(|_| "Invalid application manifest")?;
    if manifest["kind"] != "persistent_application" { return Err("Install the complete dsGPT update first".into()); }
    let value = progress("running", "Starting automatic Pixel connection…");
    let target = path()?;
    let temporary = target.with_extension("native.tmp");
    std::fs::write(&temporary, serde_json::to_vec(&value).map_err(|_| "Cannot prepare phone status")?)
        .map_err(|_| "Cannot prepare phone status")?;
    // Windows rename does not replace an existing destination. Python performs subsequent
    // atomic replacements; this initial write occurs only when no setup is running.
    std::fs::copy(&temporary, &target).map_err(|_| "Cannot prepare phone status")?;
    let _ = std::fs::remove_file(temporary);
    let mut command = Command::new(root.join("python/pythonw.exe"));
    command.args(["-B", "-I", "-m", "dsgpt_application", "pair-phone"])
        .current_dir(root).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    match command.spawn() {
        Ok(process) => { *child = Some(process); Ok(value) }
        Err(_) => {
            let failed = progress("needs_attention", "Phone setup could not start. Reinstall the complete dsGPT update and retry.");
            let _ = std::fs::write(target, serde_json::to_vec(&failed).unwrap_or_default());
            Ok(failed)
        }
    }
}
