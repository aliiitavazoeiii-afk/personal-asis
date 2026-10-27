package com.personalassist.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.MediaRecorder
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Base64
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebSettings
import android.widget.EditText
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import java.io.File

class MainActivity : ComponentActivity() {
    private lateinit var web: WebView
    private var recorder: MediaRecorder? = null
    private var recordingFile: File? = null
    private var serverUrl = ""
    private val preferences by lazy { getSharedPreferences("personal_assist", MODE_PRIVATE) }

    private val micPermission = registerForPermission { granted ->
        if (granted) startNativeRecording() else js("window.PersonalAssist.nativeStatus('permission_denied')")
    }
    private val notificationsPermission = registerForPermission { _: Boolean -> }
    private fun registerForPermission(callback: (Boolean) -> Unit): ActivityResultLauncher<String> =
        registerForActivityResult(ActivityResultContracts.RequestPermission(), callback)

    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(3, 11, 22)
        window.navigationBarColor = Color.rgb(3, 11, 22)
        web = WebView(this)
        setContentView(web)
        web.setBackgroundColor(Color.rgb(3, 11, 22))
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.cacheMode = WebSettings.LOAD_NO_CACHE
        web.settings.allowFileAccess = false
        web.settings.allowContentAccess = false
        web.settings.javaScriptCanOpenWindowsAutomatically = false
        web.settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        WebView.setWebContentsDebuggingEnabled(false)
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                return !isTrusted(request?.url)
            }
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                // Native methods are intended for the configured first-party server only.
                if (!isTrusted(Uri.parse(url ?: ""))) web.visibility = View.INVISIBLE
                else web.visibility = View.VISIBLE
            }
            override fun onReceivedSslError(view: WebView?, handler: android.webkit.SslErrorHandler?, error: android.net.http.SslError?) {
                handler?.cancel()
            }
        }
        web.addJavascriptInterface(Bridge(), "Native")
        serverUrl = preferences.getString("server_url", "") ?: ""
        if (serverUrl.isBlank()) configureServer() else loadServer()
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationsPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun isTrusted(uri: Uri?): Boolean {
        if (uri == null || serverUrl.isBlank()) return false
        val base = Uri.parse(serverUrl)
        return uri.scheme == "https" && uri.host == base.host && uri.port == base.port && uri.userInfo == null
    }
    private fun loadServer() {
        web.visibility = View.VISIBLE
        web.loadUrl(serverUrl)
    }
    private fun configureServer() {
        runOnUiThread {
            val input = EditText(this).apply {
                hint = "https://assist.example.org"
                setSingleLine(true)
                setText(serverUrl)
                setSelectAllOnFocus(true)
                setPadding(36, 20, 36, 20)
            }
            val dialog = AlertDialog.Builder(this)
                .setTitle("آدرس سرور Personal Assist")
                .setMessage("آدرس HTTPS دامنه‌ای که روی سرور خودت نصب کرده‌ای را وارد کن.")
                .setView(input)
                .setPositiveButton("اتصال", null)
                .setNegativeButton("انصراف") { _, _ -> if (serverUrl.isBlank()) finish() }
                .create()
            dialog.setOnShowListener {
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                    val entered = input.text.toString().trim().trimEnd('/')
                    val uri = Uri.parse(entered)
                    if (uri.scheme != "https" || uri.host.isNullOrBlank() || uri.userInfo != null ||
                        (uri.path != null && uri.path != "" && uri.path != "/") || uri.query != null || uri.fragment != null) {
                        input.error = "آدرس معتبر HTTPS وارد کن (بدون مسیر اضافی)"
                    } else {
                        serverUrl = entered
                        preferences.edit().putString("server_url", serverUrl).apply()
                        dialog.dismiss()
                        loadServer()
                    }
                }
            }
            dialog.show()
            dialog.setCancelable(serverUrl.isNotBlank())
        }
    }
    private fun js(code: String) = runOnUiThread { if (::web.isInitialized && isTrusted(web.url?.let(Uri::parse))) web.evaluateJavascript(code, null) }
    private fun startNativeRecording() {
        runOnUiThread {
            try {
                if (recorder != null) return@runOnUiThread
                recordingFile = File.createTempFile("assistant-", ".m4a", cacheDir)
                @Suppress("DEPRECATION")
                val m = if (Build.VERSION.SDK_INT >= 31) MediaRecorder(this) else MediaRecorder()
                m.setAudioSource(MediaRecorder.AudioSource.MIC)
                m.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                m.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                m.setAudioEncodingBitRate(64000)
                m.setAudioSamplingRate(44100)
                m.setOutputFile(recordingFile!!.absolutePath)
                m.prepare(); m.start()
                recorder = m
                js("window.PersonalAssist.nativeStatus('recording')")
            } catch (_: Exception) {
                recorder?.release(); recorder = null
                recordingFile?.delete(); recordingFile = null
                js("window.PersonalAssist.nativeStatus('error')")
            }
        }
    }
    private fun stopNativeRecording() {
        runOnUiThread {
            val m = recorder ?: return@runOnUiThread
            val file = recordingFile
            recorder = null
            recordingFile = null
            try { m.stop(); m.release() } catch (_: Exception) {
                m.release(); file?.delete(); js("window.PersonalAssist.nativeStatus('error')"); return@runOnUiThread
            }
            Thread {
                try {
                    val payload = Base64.encodeToString(file!!.readBytes(), Base64.NO_WRAP)
                    js("window.PersonalAssist.onNativeAudio('$payload')")
                } catch (_: Exception) { js("window.PersonalAssist.nativeStatus('error')") }
                finally { file?.delete() }
            }.start()
        }
    }
    inner class Bridge {
        @JavascriptInterface fun startRecording() {
            runOnUiThread {
                if (!isTrusted(web.url?.let(Uri::parse))) return@runOnUiThread
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) startNativeRecording()
                else micPermission.launch(Manifest.permission.RECORD_AUDIO)
            }
        }
        @JavascriptInterface fun stopRecording() {
            if (isTrusted(web.url?.let(Uri::parse))) stopNativeRecording()
        }
        @JavascriptInterface fun syncReminders(json: String) {
            if (!isTrusted(web.url?.let(Uri::parse)) || json.length > 128000) return
            try { ReminderScheduler.sync(this@MainActivity, json) } catch (_: Exception) { }
        }
        @JavascriptInterface fun configureServer() {
            if (isTrusted(web.url?.let(Uri::parse))) configureServer()
        }
    }
    override fun onDestroy() {
        try { recorder?.stop() } catch (_: Exception) { }
        recorder?.release(); recordingFile?.delete()
        if (::web.isInitialized) { web.removeJavascriptInterface("Native"); web.destroy() }
        super.onDestroy()
    }
}
