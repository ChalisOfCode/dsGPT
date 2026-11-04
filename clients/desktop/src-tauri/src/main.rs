#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod history_ui;
mod phone_setup;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Mutex;
use tauri::State;

#[derive(Clone, Serialize, Deserialize)]
struct Connection {
    origin: String,
    token: String,
}
#[derive(Default)]
struct Session(Mutex<Option<Connection>>);

fn validate_origin(raw: &str) -> Result<String, String> {
    let url = url::Url::parse(raw).map_err(|_| "Invalid backend address")?;
    let host = url.host_str().unwrap_or("");
    let local = ["localhost", "127.0.0.1", "[::1]"].contains(&host);
    if !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
        || !((local && url.scheme() == "http")
            || (host.ends_with(".ts.net") && url.scheme() == "https"))
    {
        return Err("Use a local HTTP or HTTPS Tailscale origin".into());
    }
    Ok(url.origin().ascii_serialization())
}
fn http() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|_| "Transport initialization failed".into())
}
#[cfg(windows)]
fn credential() -> Result<keyring::Entry, String> {
    // An explicit acceptance process must never read or replace the user's connection.
    let service = match std::env::var("DSGPT_ACCEPTANCE_RUN_ID") {
        Ok(id) if id.len() == 32 && id.chars().all(|c| c.is_ascii_hexdigit()) =>
            format!("dsGPT-acceptance-{}", id),
        Ok(_) => return Err("Invalid acceptance run identity".into()),
        Err(_) => "dsGPT".to_string(),
    };
    keyring::Entry::new(&service, "backend-connection")
        .map_err(|_| "Windows credential storage unavailable".into())
}
#[cfg(windows)]
fn save_connection(c: &Connection) -> Result<(), String> {
    credential()?
        .set_password(&serde_json::to_string(c).map_err(|_| "Credential encoding failed")?)
        .map_err(|_| "Could not save credential".into())
}
#[cfg(not(windows))]
fn save_connection(_: &Connection) -> Result<(), String> {
    Err("This native client requires Windows".into())
}

#[tauri::command]
async fn connect(origin: String, token: String, state: State<'_, Session>) -> Result<(), String> {
    if token.len() < 32 || token.len() > 200 {
        return Err("Invalid credential".into());
    }
    let c = Connection {
        origin: validate_origin(&origin)?,
        token,
    };
    let response = http()?
        .get(format!("{}/v1/models", c.origin))
        .bearer_auth(&c.token)
        .send()
        .await
        .map_err(|_| "Backend unavailable")?;
    if !response.status().is_success() {
        return Err("Backend rejected connection".into());
    }
    save_connection(&c)?;
    *state.0.lock().map_err(|_| "Session unavailable")? = Some(c);
    Ok(())
}
#[tauri::command]
fn restore_connection(state: State<'_, Session>) -> Result<Option<String>, String> {
    #[cfg(windows)]
    {
        let encoded = match credential()?.get_password() {
            Ok(value) => value,
            Err(keyring::Error::NoEntry) => return Ok(None),
            Err(_) => return Err("Could not read Windows credential".into()),
        };
        let mut c: Connection =
            serde_json::from_str(&encoded).map_err(|_| "Stored connection invalid")?;
        c.origin = validate_origin(&c.origin)?;
        let origin = c.origin.clone();
        *state.0.lock().map_err(|_| "Session unavailable")? = Some(c);
        return Ok(Some(origin));
    }
    #[cfg(not(windows))]
    {
        let _ = state;
        Ok(None)
    }
}
#[tauri::command]
fn disconnect(state: State<'_, Session>) -> Result<(), String> {
    #[cfg(windows)]
    match credential()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => {}
        Err(_) => return Err("Could not remove credential".into()),
    }
    *state.0.lock().map_err(|_| "Session unavailable")? = None;
    Ok(())
}

fn public_source_url(raw: &str) -> Result<String, String> {
    if raw.len() > 4096 || raw.chars().any(|c| c <= ' ' || c == '\\') {
        return Err("Invalid source URL".into());
    }
    let url = url::Url::parse(raw).map_err(|_| "Invalid source URL")?;
    let host = url.host_str().unwrap_or("");
    if url.scheme() != "https" || !url.username().is_empty() || url.password().is_some()
        || url.port().is_some() || !host.contains('.') || host.ends_with('.')
        || host.parse::<std::net::IpAddr>().is_ok() || host.contains(':')
        || [".local", ".localhost", ".internal", ".invalid"].iter().any(|s| host.ends_with(s)) {
        return Err("Only public HTTPS source domains can be opened".into());
    }
    Ok(url.to_string())
}

#[tauri::command]
fn open_public_source(url: String) -> Result<(), String> {
    let validated = public_source_url(&url)?;
    #[cfg(windows)]
    {
        #[link(name = "shell32")]
        extern "system" {
            fn ShellExecuteW(window: *mut std::ffi::c_void, operation: *const u16,
                file: *const u16, parameters: *const u16, directory: *const u16,
                show: i32) -> *mut std::ffi::c_void;
        }
        let operation: Vec<u16> = "open\0".encode_utf16().collect();
        let target: Vec<u16> = validated.encode_utf16().chain(std::iter::once(0)).collect();
        // Direct OS URL association, never a shell command or authenticated API request.
        let result = unsafe { ShellExecuteW(std::ptr::null_mut(), operation.as_ptr(),
            target.as_ptr(), std::ptr::null(), std::ptr::null(), 1) };
        if result as usize <= 32 { return Err("Could not open the system browser".into()); }
        Ok(())
    }
    #[cfg(not(windows))]
    { let _ = validated; Err("This native client requires Windows".into()) }
}
#[tauri::command]
async fn api_request(
    path: String,
    method: String,
    body: Value,
    state: State<'_, Session>,
) -> Result<Value, String> {
    if !path.starts_with("/v1/")
        || path.contains("..")
        || path.contains('\\')
        || path.contains('#')
        || path.contains('\r')
        || path.contains('\n')
    {
        return Err("Invalid API path".into());
    }
    let method = match method.as_str() {
        "GET" => reqwest::Method::GET,
        "POST" => reqwest::Method::POST,
        "PUT" => reqwest::Method::PUT,
        "PATCH" => reqwest::Method::PATCH,
        "DELETE" => reqwest::Method::DELETE,
        _ => return Err("Method unavailable".into()),
    };
    let c = state
        .0
        .lock()
        .map_err(|_| "Session unavailable")?
        .clone()
        .ok_or("Connect first")?;
    let mut request = http()?
        .request(method, format!("{}{}", c.origin, path))
        .bearer_auth(&c.token);
    if !body.is_null() {
        request = request.json(&body)
    }
    let mut response = request.send().await.map_err(|_| "Backend unavailable")?;
    if !response.status().is_success() {
        let status = response.status().as_u16();
        if status == 401 { return Err("Connection expired. Reconnect in Settings.".into()); }
        let mut data = Vec::new();
        while let Ok(Some(chunk)) = response.chunk().await {
            if data.len() + chunk.len() > 16384 { data.clear(); break; }
            data.extend_from_slice(&chunk);
        }
        let value: Value = serde_json::from_slice(&data).unwrap_or(Value::Null);
        let detail = value["detail"].as_str().or_else(|| value["detail"]["code"].as_str())
            .unwrap_or("Refresh the current state before retrying.");
        return Err(format!("Request failed ({}). {}", status, detail.chars().take(300).collect::<String>()));
    }
    response
        .json()
        .await
        .map_err(|_| "Invalid backend response".into())
}
#[tauri::command]
async fn download_diagnostics(
    id: String,
    sha256: String,
    state: State<'_, Session>,
) -> Result<(), String> {
    if id.len() != 36
        || !id.chars().all(|c| c.is_ascii_hexdigit() || c == '-')
        || sha256.len() != 64
        || !sha256.chars().all(|c| c.is_ascii_hexdigit())
    {
        return Err("Invalid export identity".into());
    }
    let c = state
        .0
        .lock()
        .map_err(|_| "Session unavailable")?
        .clone()
        .ok_or("Connect first")?;
    let response = http()?
        .get(format!(
            "{}/v1/diagnostics/exports/{}?sha256={}",
            c.origin, id, sha256
        ))
        .bearer_auth(&c.token)
        .send()
        .await
        .map_err(|_| "Backend unavailable")?;
    if !response.status().is_success() {
        return Err("Preview expired. Preview again before saving.".into());
    }
    let data = response
        .bytes()
        .await
        .map_err(|_| "Export download failed")?;
    let Some(file) = rfd::AsyncFileDialog::new()
        .set_file_name("dsGPT-Diagnostics.zip")
        .add_filter("ZIP archive", &["zip"])
        .save_file()
        .await
    else {
        return Ok(());
    };
    file.write(&data)
        .await
        .map_err(|_| "Unable to save export".into())
}
#[tauri::command]
async fn download_work(id: String, state: State<'_, Session>) -> Result<bool, String> {
    if id.len() != 36 || !id.chars().enumerate().all(|(i, c)|
        if [8, 13, 18, 23].contains(&i) { c == '-' } else { c.is_ascii_hexdigit() }) {
        return Err("Invalid task identity".into());
    }
    let c = state.0.lock().map_err(|_| "Session unavailable")?.clone().ok_or("Connect first")?;
    let mut response = http()?.get(format!("{}/v1/work/tasks/{}/export", c.origin, id))
        .bearer_auth(&c.token).send().await.map_err(|_| "Backend unavailable")?;
    if !response.status().is_success() { return Err("Source download failed. Refresh the task and retry.".into()); }
    let mut data = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "Source download interrupted")? {
        if data.len() + chunk.len() > 32 * 1024 * 1024 { return Err("Source archive exceeds the download limit".into()); }
        data.extend_from_slice(&chunk);
    }
    let Some(file) = rfd::AsyncFileDialog::new().set_file_name("dsGPT-project.zip")
        .add_filter("ZIP archive", &["zip"]).save_file().await else { return Ok(false); };
    file.write(&data).await.map_err(|_| "Unable to save source archive")?;
    Ok(true)
}
#[tauri::command]
async fn download_artifact(task_id: String, id: String, sha256: String, bytes: usize,
    extension: String, state: State<'_, Session>) -> Result<bool, String> {
    use sha2::{Digest, Sha256};
    for value in [&task_id, &id] {
        if value.len() != 36 || !value.chars().enumerate().all(|(i, c)|
            if [8, 13, 18, 23].contains(&i) { c == '-' } else { c.is_ascii_hexdigit() }) {
            return Err("Invalid artifact identity".into());
        }
    }
    if bytes > 256 * 1024 * 1024 || sha256.len() != 64 || !sha256.bytes().all(|c| c.is_ascii_hexdigit())
        || !["apk", "exe", "bin"].contains(&extension.as_str()) {
        return Err("Invalid artifact metadata".into());
    }
    let c = state.0.lock().map_err(|_| "Session unavailable")?.clone().ok_or("Connect first")?;
    let mut response = http()?.get(format!("{}/v1/work/tasks/{}/artifacts/{}", c.origin, task_id, id))
        .bearer_auth(&c.token).send().await.map_err(|_| "Backend unavailable")?;
    if !response.status().is_success() { return Err("Artifact download failed".into()); }
    let mut data = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "Artifact download interrupted")? {
        if data.len() + chunk.len() > bytes { return Err("Artifact size mismatch".into()); }
        data.extend_from_slice(&chunk);
    }
    if data.len() != bytes || format!("{:x}", Sha256::digest(&data)) != sha256 {
        return Err("Artifact integrity check failed".into());
    }
    let Some(file) = rfd::AsyncFileDialog::new().set_file_name(format!("dsGPT-artifact.{}", extension))
        .save_file().await else { return Ok(false); };
    file.write(&data).await.map_err(|_| "Unable to save artifact")?;
    Ok(true)
}
#[tauri::command]
async fn download_memory(task_id: Option<String>, state: State<'_, Session>) -> Result<bool, String> {
    let query = if let Some(id) = task_id {
        if id.len() != 36 || !id.chars().enumerate().all(|(i, c)|
            if [8, 13, 18, 23].contains(&i) { c == '-' } else { c.is_ascii_hexdigit() }) {
            return Err("Invalid project identity".into());
        }
        format!("?task_id={}", id)
    } else { String::new() };
    let c = state.0.lock().map_err(|_| "Session unavailable")?.clone().ok_or("Connect first")?;
    let mut response = http()?.get(format!("{}/v1/memories/export{}", c.origin, query))
        .bearer_auth(&c.token).send().await.map_err(|_| "Backend unavailable")?;
    if !response.status().is_success() { return Err("Memory export failed. Refresh and retry.".into()); }
    let mut data = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "Memory export interrupted")? {
        if data.len() + chunk.len() > 32 * 1024 * 1024 { return Err("Memory export exceeds the 32 MiB download limit".into()); }
        data.extend_from_slice(&chunk);
    }
    let Some(file) = rfd::AsyncFileDialog::new().set_file_name("dsGPT-memory.json")
        .add_filter("JSON document", &["json"]).save_file().await else { return Ok(false); };
    file.write(&data).await.map_err(|_| "Unable to save memory export")?;
    Ok(true)
}
#[tauri::command]
async fn pick_text_attachment() -> Result<Option<Value>, String> {
    use std::io::Read;
    let Some(file) = rfd::AsyncFileDialog::new().set_title("Choose a UTF-8 text/code file (64 KiB maximum)")
        .pick_file().await else { return Ok(None); };
    let name = file.file_name();
    let input = std::fs::File::open(file.path()).map_err(|_| "Unable to read selected file")?;
    let metadata = input.metadata().map_err(|_| "Unable to inspect selected file")?;
    if !metadata.is_file() || metadata.len() > 65536 { return Err("Choose a regular text file no larger than 64 KiB".into()); }
    let mut data = Vec::new(); input.take(65537).read_to_end(&mut data).map_err(|_| "Unable to read selected file")?;
    if data.len() > 65536 { return Err("Selected file exceeds 64 KiB".into()); }
    let text = String::from_utf8(data).map_err(|_| "Selected file is not valid UTF-8 text")?;
    Ok(Some(serde_json::json!({"name": name, "text": text})))
}
#[tauri::command]
async fn pick_document_attachment(work: Option<bool>) -> Result<Option<Value>, String> {
    use std::io::Read;
    let mut formats = vec!["docx", "pdf", "png", "jpg", "jpeg", "webp", "xlsx", "pptx"];
    if work.unwrap_or(false) { formats.push("zip"); }
    let Some(file) = rfd::AsyncFileDialog::new().set_title("Choose a document or image (512 KiB)")
        .add_filter("Documents and images", &formats).pick_file().await else { return Ok(None); };
    let name = file.file_name();
    let input = std::fs::File::open(file.path()).map_err(|_| "Unable to read document")?;
    let metadata = input.metadata().map_err(|_| "Unable to inspect document")?;
    if !metadata.is_file() || metadata.len() > 524288 { return Err("Choose a regular file no larger than 512 KiB".into()); }
    let mut bytes=Vec::new(); input.take(524289).read_to_end(&mut bytes).map_err(|_| "Unable to read document")?;
    if bytes.len()>524288 {return Err("Document exceeds 512 KiB".into());}
    Ok(Some(serde_json::json!({"name":name,"bytes":bytes})))
}
#[tauri::command]
async fn download_attachment(chat_id: String, id: String, name: String, state: State<'_, Session>) -> Result<bool, String> {
    for value in [&chat_id, &id] {
        if value.len() != 36 || !value.chars().enumerate().all(|(i, c)| if [8,13,18,23].contains(&i) { c == '-' } else { c.is_ascii_hexdigit() }) { return Err("Invalid attachment identity".into()); }
    }
    if name.is_empty() || name.chars().count() > 160 || name.chars().any(|c| c.is_control() || r#"/\:<>"|?*"#.contains(c)) || (name.ends_with(' ') || name.ends_with('.')) { return Err("Invalid attachment filename".into()); }
    let c = state.0.lock().map_err(|_| "Session unavailable")?.clone().ok_or("Connect first")?;
    let mut response = http()?.get(format!("{}/v1/conversations/{}/attachments/{}/download", c.origin, chat_id, id)).bearer_auth(&c.token).send().await.map_err(|_| "Backend unavailable")?;
    if !response.status().is_success() { return Err("Attachment unavailable. Refresh history.".into()); }
    let mut data = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "Attachment download interrupted")? {
        if data.len() + chunk.len() > 524288 { return Err("Attachment exceeds 512 KiB".into()); } data.extend_from_slice(&chunk);
    }
    let Some(file) = rfd::AsyncFileDialog::new().set_file_name(&name).save_file().await else { return Ok(false); };
    file.write(&data).await.map_err(|_| "Unable to save attachment")?; Ok(true)
}
fn main() {
    let mut context = tauri::generate_context!();
    #[cfg(windows)]
    let acceptance = std::env::var("DSGPT_ACCEPTANCE_RUN_ID").ok().map(|id| {
        assert!(id.len() == 32 && id.chars().all(|c| c.is_ascii_hexdigit()),
            "Invalid acceptance run identity");
        let port: u16 = std::env::var("DSGPT_ACCEPTANCE_DEBUG_PORT")
            .expect("Missing acceptance port").parse().expect("Invalid acceptance port");
        assert!(port >= 1024, "Invalid acceptance port");
        let profile = std::path::PathBuf::from(std::env::var("DSGPT_ACCEPTANCE_PROFILE")
            .expect("Missing acceptance profile"));
        assert!(profile.is_absolute() && profile.file_name().and_then(|p| p.to_str()) ==
            Some(format!("webview-{}", id).as_str()), "Invalid acceptance profile");
        for window in &mut context.config_mut().app.windows { window.create = false; }
        (port, profile)
    });
    tauri::Builder::default()
        .setup(move |app| {
            #[cfg(windows)]
            if let Some((port, profile)) = &acceptance {
                // Configure only this explicit, isolated acceptance window through the API.
                // Current WebView2 ignores environment-only debug flags on elevated hosts.
                for config in &app.config().app.windows {
                    tauri::WebviewWindowBuilder::from_config(app.handle(), config)?
                        .data_directory(profile.clone())
                        .additional_browser_args(&format!(
                            "--remote-debugging-port={} --remote-debugging-address=127.0.0.1", port))
                        .build()?;
                }
            }
            Ok(())
        })
        .manage(Session::default())
        .manage(phone_setup::PhoneSetup::default())
        .manage(history_ui::HistorySelection::default())
        .invoke_handler(tauri::generate_handler![
            phone_setup::start_phone_setup,
            phone_setup::phone_setup_status,
            history_ui::preview_history_import,
            history_ui::apply_history_import,
            connect,
            restore_connection,
            disconnect,
            api_request,
            open_public_source,
            download_work,
            download_artifact,
            download_memory,
            pick_text_attachment,
            pick_document_attachment,
            download_attachment,
            download_diagnostics
        ])
        .run(context)
        .expect("Unable to start dsGPT");
}
