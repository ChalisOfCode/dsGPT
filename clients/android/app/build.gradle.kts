plugins { id("com.android.application"); id("org.jetbrains.kotlin.android"); id("org.jetbrains.kotlin.plugin.compose") }
// CI always builds an unsigned production release and a separate acceptance app.
// Never silently substitute a new debug key for the installed production identity.
tasks.matching { it.name == "packageDebug" }.configureEach {
 doFirst {
  if (!providers.gradleProperty("acceptance").isPresent && System.getenv("DSGPT_DEBUG_KEY").isNullOrBlank()) {
   throw GradleException("Production debug APK needs the existing signing key. Use -Pacceptance for disposable tests or assembleRelease for an unsigned release input.")
  }
 }
}
android {
 namespace = "com.dsgpt.mobile"
 compileSdk = 35
 defaultConfig { applicationId = "com.dsgpt.mobile"; minSdk = 26; targetSdk = 35; versionCode = 23; versionName = "0.9.0" }
 defaultConfig { testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner" }
 defaultConfig { buildConfigField("boolean", "ACCEPTANCE", "false") }
 // Built only by the acceptance job; it cannot replace the user's installed app.
 if (providers.gradleProperty("acceptance").isPresent) {
  defaultConfig {
   applicationId = "com.dsgpt.mobile.acceptance"
   buildConfigField("boolean", "ACCEPTANCE", "true")
  }
  sourceSets.getByName("main").manifest.srcFile("src/acceptance/AndroidManifest.xml")
  sourceSets.getByName("main").res.srcDir("src/acceptance/res")
 }
 signingConfigs.getByName("debug") {
  System.getenv("DSGPT_DEBUG_KEY")?.let { storeFile = file(it); storePassword = "android"; keyAlias = "androiddebugkey"; keyPassword = "android" }
 }
 buildFeatures { compose = true; buildConfig = true }
 compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
 kotlinOptions { jvmTarget = "17" }
 testOptions { unitTests.isIncludeAndroidResources = true }
}
dependencies {
 implementation(platform("androidx.compose:compose-bom:2025.05.01"))
 implementation("androidx.activity:activity-compose:1.10.1")
 implementation("androidx.compose.material3:material3")
 implementation("androidx.compose.foundation:foundation")
 implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.1")
 implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.1")
 implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
 implementation("com.squareup.okhttp3:okhttp:4.12.0")
 testImplementation("junit:junit:4.13.2")
 testImplementation("org.robolectric:robolectric:4.16.1")
 testImplementation("androidx.compose.ui:ui-test-junit4")
 debugImplementation("androidx.compose.ui:ui-test-manifest")
 androidTestImplementation("androidx.test:runner:1.6.2")
 androidTestImplementation("androidx.test:core:1.6.1")
 androidTestImplementation("androidx.test.ext:junit:1.2.1")
}

