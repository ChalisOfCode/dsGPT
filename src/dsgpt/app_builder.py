"""Reviewed project scaffolds; the model implements the requested features on top."""

# Embedded Kotlin, C++ and XML retain their natural formatting.
# ruff: noqa: E501
import json
from html import escape
from pathlib import Path

GRADLE_VERSION = "8.13"
AGP_VERSION = "8.10.1"
KOTLIN_VERSION = "2.1.20"


def project_files(platform, name, project_id):
    app_id = "com.dsgpt.generated.p" + project_id.replace("-", "")
    label = json.dumps(name, ensure_ascii=False).replace("$", "\\$")
    if platform == "android":
        return {
            "android/settings.gradle": """pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }
rootProject.name = 'GeneratedApp'
include ':app'
""",
            "android/build.gradle": f"""plugins {{
    id 'com.android.application' version '{AGP_VERSION}' apply false
    id 'org.jetbrains.kotlin.android' version '{KOTLIN_VERSION}' apply false
    id 'org.jetbrains.kotlin.plugin.compose' version '{KOTLIN_VERSION}' apply false
}}
""",
            "android/gradle.properties": """org.gradle.jvmargs=-Xmx768m -XX:ActiveProcessorCount=2 -Dfile.encoding=UTF-8
org.gradle.workers.max=2
org.gradle.parallel=false
org.gradle.daemon=false
kotlin.compiler.execution.strategy=in-process
android.useAndroidX=true
""",
            "android/app/build.gradle": f"""plugins {{ id 'com.android.application'; id 'org.jetbrains.kotlin.android'; id 'org.jetbrains.kotlin.plugin.compose' }}
android {{
    namespace '{app_id}'
    compileSdk 35
    defaultConfig {{ applicationId '{app_id}'; minSdk 26; targetSdk 35; versionCode 1; versionName '1.0' }}
    buildFeatures {{ compose true; buildConfig true }}
    compileOptions {{ sourceCompatibility JavaVersion.VERSION_17; targetCompatibility JavaVersion.VERSION_17 }}
    kotlinOptions {{ jvmTarget = '17' }}
    testOptions {{ unitTests.all {{ maxHeapSize = '256m' }} }}
}}
dependencies {{
    implementation platform('androidx.compose:compose-bom:2025.05.01')
    implementation 'androidx.activity:activity-compose:1.10.1'
    implementation 'androidx.compose.material3:material3'
    implementation 'androidx.compose.foundation:foundation'
    implementation 'androidx.lifecycle:lifecycle-runtime-compose:2.9.1'
    implementation 'androidx.lifecycle:lifecycle-viewmodel-compose:2.9.1'
    implementation 'org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2'
    implementation 'com.squareup.okhttp3:okhttp:4.12.0'
    testImplementation 'junit:junit:4.13.2'
}}
""",
            "android/app/src/main/AndroidManifest.xml": f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:label="{escape(name, quote=True)}" android:allowBackup="false" android:supportsRtl="true" android:theme="@android:style/Theme.Material.Light.NoActionBar">
        <activity android:name=".MainActivity" android:exported="true" android:windowSoftInputMode="adjustResize">
            <intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter>
        </activity>
    </application>
</manifest>
''',
            "android/app/src/main/java/"
            + app_id.replace(".", "/")
            + "/MainActivity.kt": f"""package {app_id}

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {{
    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        setContent {{
            MaterialTheme {{
                Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(24.dp)) {{
                    Text({label}, style = MaterialTheme.typography.headlineMedium)
                    Text("Implement the requested features before delivery.")
                }}
            }}
        }}
    }}
}}
""",
            "android/README.md": "Build with dsGPT's build_project tool. Implement the full specification and add meaningful JUnit tests under app/src/test/java. The initial screen is only a scaffold. Preserve the applicationId for updates; increment versionCode. Physical phone testing is separate from build and unit-test results.\n",
        }
    if platform == "windows":
        title = json.dumps(name, ensure_ascii=False)
        return {
            "windows/main.cpp": f"""#define UNICODE
#define _UNICODE
#include <windows.h>

LRESULT CALLBACK WindowProcedure(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {{
    if (message == WM_DESTROY) {{ PostQuitMessage(0); return 0; }}
    return DefWindowProcW(window, message, wparam, lparam);
}}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int show) {{
    WNDCLASSW wc = {{}};
    wc.lpfnWndProc = WindowProcedure;
    wc.hInstance = instance;
    wc.lpszClassName = L"dsGPTGeneratedWindow";
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
    RegisterClassW(&wc);
    HWND window = CreateWindowExW(0, wc.lpszClassName, L{title}, WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT, CW_USEDEFAULT, 900, 640, nullptr, nullptr, instance, nullptr);
    if (!window) return 1;
    ShowWindow(window, show);
    MSG message;
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {{ TranslateMessage(&message); DispatchMessageW(&message); }}
    return static_cast<int>(message.wParam);
}}
""",
            "windows/README.md": "Native Windows GUI scaffold, built with MinGW C++17. Implement requested features in main.cpp and additional .cpp/.h files. Put portable behavior tests in tests.cpp (a main() returning nonzero on failure). build_project compiles/runs those tests on Linux, then cross-compiles the EXE. Native Windows behavior remains untested until exercised on Windows.\n",
        }
    raise ValueError("unknown_app_platform")


def scaffold(db, task_id, action):
    from .project_tools import MAX_FILES, MAX_PROJECT_BYTES, ProjectAction, ProjectTools

    generated = project_files(action.platform, action.title or "My App", task_id)
    existing = {r[0] for r in db.execute("SELECT path FROM work_files WHERE task_id=?", (task_id,))}
    if any(path.casefold() in {p.casefold() for p in existing} for path in generated):
        return {
            "error": "scaffold_already_exists",
            "help": "Read and edit the existing project; do not scaffold over it.",
        }
    size = db.execute(
        "SELECT coalesce(sum(length(CAST(content AS BLOB))),0) FROM work_files WHERE task_id=?",
        (task_id,),
    ).fetchone()[0]
    if (
        len(existing) + len(generated) > MAX_FILES
        or size + sum(len(v.encode()) for v in generated.values()) > MAX_PROJECT_BYTES
    ):
        return {"error": "project_storage_limit"}
    db.execute("SAVEPOINT scaffold")
    output = []
    for path, content in generated.items():
        result = ProjectTools.apply(
            db,
            task_id,
            ProjectAction(
                tool="write_file", path=path, content=content, summary="Reviewed app scaffold"
            ),
        )
        if "error" in result:
            db.execute("ROLLBACK TO scaffold")
            db.execute("RELEASE scaffold")
            return result
        output.append(result)
    db.execute("RELEASE scaffold")
    return {
        "platform": action.platform,
        "files": output,
        "next": "Read the scaffold, implement the original requirements, add feature tests, then use build_project. A scaffold is not a finished app.",
    }


def cache_project(directory):
    root = Path(directory)
    for path, content in project_files(
        "android", "Toolchain Check", "00000000-0000-0000-0000-000000000000"
    ).items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    path = root / "android/app/src/test/java/ToolchainTest.kt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "import org.junit.Test\nimport org.junit.Assert.assertEquals\nclass ToolchainTest { @Test fun compilerWorks() { assertEquals(4, 2 + 2) } }\n"
    )


if __name__ == "__main__":
    import sys

    cache_project(sys.argv[1])
