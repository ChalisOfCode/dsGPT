package com.dsgpt.mobile

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import org.json.JSONObject

@Composable
fun WorkDocumentEvidence(detail: String) {
    val value = remember(detail) {
        runCatching { JSONObject(detail).opt("document_validation_summary") as? String }.getOrNull()
    }
    if(value != null && value.length <= 2000) Text(value)
}
