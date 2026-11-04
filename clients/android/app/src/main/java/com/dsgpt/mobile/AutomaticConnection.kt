package com.dsgpt.mobile

data class AutomaticConnectionResult(val status: String, val deviceId: String? = null)

/** Keep a working credential, and never replace another desktop or an offline connection. */
suspend fun <T> automaticConnection(
    origin: String,
    load: () -> T?,
    address: (T) -> String,
    identity: suspend (T) -> String?,
    pair: suspend () -> T,
    save: (T) -> Unit,
): AutomaticConnectionResult {
    val existing = load()
    if (existing != null && address(existing) != origin) return AutomaticConnectionResult("different_desktop")
    val known = existing?.let { identity(it) }
    if (known != null) return AutomaticConnectionResult("reused", known)
    val connected = pair()
    val verified = identity(connected) ?: error("Pairing expired")
    check(verified.matches(Regex("[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}")))
    save(connected)
    check(load()?.let(address) == origin)
    return AutomaticConnectionResult("paired", verified)
}
