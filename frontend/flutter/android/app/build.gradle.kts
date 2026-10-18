plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

import java.util.Properties
import java.nio.charset.StandardCharsets
import java.util.Base64

val localProperties = Properties().apply {
    val propertiesFile = rootProject.file("local.properties")
    if (propertiesFile.exists()) propertiesFile.inputStream().use(::load)
}

fun flutterDartDefine(name: String): String? {
    val encodedDefines = project.findProperty("dart-defines") as String? ?: return null
    return encodedDefines.split(',')
        .mapNotNull { encoded ->
            runCatching {
                String(Base64.getDecoder().decode(encoded), StandardCharsets.UTF_8)
            }.getOrNull()
        }
        .firstOrNull { value -> value.startsWith("$name=") }
        ?.substringAfter('=')
        ?.takeIf { value -> value.isNotEmpty() }
}

// Flutter supplies this value with --dart-define.  The Android callback is
// resolved by Gradle, so it must receive the same value as KakaoSdk.init.
val kakaoNativeAppKey =
    System.getenv("KAKAO_NATIVE_APP_KEY")
        ?.takeIf { it.isNotEmpty() }
        ?: localProperties.getProperty("KAKAO_NATIVE_APP_KEY")
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
        ?: flutterDartDefine("KAKAO_NATIVE_APP_KEY")
        ?: ""

fun requiredNaverProperty(name: String): String =
    localProperties.getProperty(name)?.trim()?.takeIf { it.isNotEmpty() }
        ?: error("$name must be configured in android/local.properties")

val naverClientId = requiredNaverProperty("NAVER_CLIENT_ID")
val naverClientSecret = requiredNaverProperty("NAVER_CLIENT_SECRET")
val naverClientName = requiredNaverProperty("NAVER_CLIENT_NAME")

android {
    namespace = "com.example.travel_mate"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.example.travel_mate"
        multiDexEnabled = true

        manifestPlaceholders["KAKAO_NATIVE_APP_KEY"] = kakaoNativeAppKey
        buildConfigField("String", "NAVER_CLIENT_ID", "\"$naverClientId\"")
        buildConfigField("String", "NAVER_CLIENT_SECRET", "\"$naverClientSecret\"")
        buildConfigField("String", "NAVER_CLIENT_NAME", "\"$naverClientName\"")
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
            // R8 shrinking crashed the release app at launch on Android 10
            // (SM-G960N: ExceptionInInitializerError cast in a coroutine).
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")
    implementation("com.navercorp.nid:oauth:5.12.0")
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
