package com.dsgpt.mobile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.IconButton
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.widthIn
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import java.util.Locale

class DictationDraft(private val original: String) {
    private var committed = ""
    fun partial(words: String) = listOf(original.trimEnd(), committed, words).filter { it.isNotBlank() }.joinToString(" ")
    fun finish(words: String): String {
        committed = listOf(committed, words).filter { it.isNotBlank() }.joinToString(" ")
        return partial("")
    }
}

@Composable
fun LiveDictation(value: String, enabled: Boolean = true, onValue: (String) -> Unit,
                  compact: Boolean = false,
                  onListening: (Boolean) -> Unit = {}) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    val currentValue by rememberUpdatedState(value)
    val change by rememberUpdatedState(onValue)
    val listeningChanged by rememberUpdatedState(onListening)
    var listening by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf("") }
    var showNotice by remember { mutableStateOf(false) }
    var recognizer by remember { mutableStateOf<SpeechRecognizer?>(null) }
    var lastWritten by remember { mutableStateOf(value) }
    var epoch by remember { mutableIntStateOf(0) }
    val handler = remember { Handler(Looper.getMainLooper()) }
    fun cancel() {
        epoch++; listening = false; listeningChanged(false)
        handler.removeCallbacksAndMessages(null)
        recognizer?.cancel(); recognizer?.destroy(); recognizer = null
    }
    fun start() {
        cancel()
        if (Build.VERSION.SDK_INT < 31 || !SpeechRecognizer.isOnDeviceRecognitionAvailable(context)) {
            notice = "On-device dictation is unavailable. Enable/download your phone’s on-device speech service first; no audio was sent to a cloud service."
            return
        }
        val own = ++epoch
        val draft = DictationDraft(currentValue)
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toLanguageTag())
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        val speech = SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
        recognizer = speech; listening = true; listeningChanged(true); lastWritten = currentValue
        notice = "Listening on this phone — words appear as you speak."
        fun publish(text: String) { if (epoch == own) { lastWritten = text; change(text) } }
        fun again() {
            if (listening && epoch == own) handler.postDelayed({
                if (listening && epoch == own) speech.startListening(intent)
            }, 300)
        }
        speech.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
            override fun onPartialResults(results: Bundle?) {
                results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { publish(draft.partial(it)) }
            }
            override fun onResults(results: Bundle?) {
                results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { publish(draft.finish(it)) }
                if (listening) again() else if (epoch == own) { listeningChanged(false); speech.destroy(); recognizer = null }
            }
            override fun onError(error: Int) {
                if (epoch != own) return
                if (listening && error in listOf(SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT)) { again(); return }
                if (Build.VERSION.SDK_INT >= 33 && error == SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE) {
                    speech.triggerModelDownload(intent)
                    notice = "Downloading the phone’s offline speech language. Tap Dictate again when the download finishes."
                } else notice = "Dictation stopped (speech service $error). Your visible text is preserved; tap Dictate to retry."
                cancel()
            }
        })
        try { speech.startListening(intent) }
        catch (_: Exception) { notice = "Could not start on-device speech. Check microphone access and the phone’s speech language."; cancel() }
        handler.postDelayed({ if (epoch == own) { notice = "Ten-minute recording finished. Your text is ready to edit."; cancel() } }, 600000)
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) start() else notice = "Allow dsGPT microphone access to use live dictation."
    }
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP) cancel() }
        lifecycle.lifecycle.addObserver(observer)
        onDispose { cancel(); lifecycle.lifecycle.removeObserver(observer) }
    }
    LaunchedEffect(value, enabled) {
        if (!enabled || (recognizer != null && value != lastWritten)) cancel()
    }
    val toggle: () -> Unit = {
            if (listening) {
                listening = false; recognizer?.stopListening()
                val finishing = epoch
                handler.postDelayed({ if(epoch == finishing && !listening) cancel() }, 5000)
                notice = "Dictation finished. Review and edit your words before sending."
            } else if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) start()
            else permission.launch(Manifest.permission.RECORD_AUDIO)
    }
    androidx.compose.foundation.layout.Column {
        if (compact) IconButton(enabled = enabled, onClick = toggle,
            modifier = Modifier.semantics { contentDescription = if (listening) "Stop dictation" else "Dictate" }) {
            Text(if (listening) "■" else "🎙")
        } else TextButton(enabled = enabled, onClick = toggle) { Text(if (listening) "■ Stop dictation" else "🎙 Dictate") }
        if (notice.isNotBlank()) Text(notice,
            modifier = if (compact) Modifier.widthIn(max = 80.dp).clickable { showNotice = true } else Modifier,
            maxLines = if (compact) 1 else Int.MAX_VALUE,
            overflow = TextOverflow.Ellipsis,
            style = androidx.compose.material3.MaterialTheme.typography.labelSmall)
    }
    if (showNotice) AlertDialog(onDismissRequest = { showNotice = false },
        title = { Text("Dictation") }, text = { Text(notice) },
        confirmButton = { TextButton(onClick = { showNotice = false }) { Text("Done") } })
}

