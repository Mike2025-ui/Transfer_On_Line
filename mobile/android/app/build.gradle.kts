plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.example.gateway_apk"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.example.gateway_apk"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        // Pinned explicitly rather than inherited from flutter.targetSdkVersion:
        // Android 15 (API 35) caps dataSync-typed foreground services at ~6
        // cumulative hours per rolling 24h window, and that cap is keyed to
        // the app's *declared* targetSdk, not the device's real OS version.
        // This app must run its GatewayForegroundService 24/7 - staying on
        // 34 avoids that cap regardless of which Android version the
        // sideloaded phone is actually running. Revisit deliberately, not by
        // just bumping the Flutter SDK, once Service.onTimeout() handling
        // (API 35's graceful-shutdown hook) has been implemented and tested.
        targetSdk = 34
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

dependencies {
    // Watchdog (GatewayWatchdogWorker) - periodic self-healing check that
    // restarts GatewayForegroundService if it died. Plain Kotlin Worker, no
    // Flutter engine involved, see the class doc for why.
    implementation("androidx.work:work-runtime-ktx:2.9.1")

    // Phase D3 : uniquement pour la logique pure sans dépendance Android
    // (classifyResult - voir ClassifyResultTest.kt). Délibérément PAS de
    // Mockito/Robolectric : un AccessibilityNodeInfo simulé ne prouverait
    // rien du comportement réel (voir le rapport D3, le test réel sur
    // l'Itel A80 est l'unique preuve pour tout ce qui touche l'arbre
    // Accessibility).
    testImplementation("junit:junit:4.13.2")
}

flutter {
    source = "../.."
}
