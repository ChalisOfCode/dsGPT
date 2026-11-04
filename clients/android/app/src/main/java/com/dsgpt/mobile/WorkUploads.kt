package com.dsgpt.mobile

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

suspend fun uploadWorkFile(app: Application, api: Api, uri: Uri, progress: (String) -> Unit): DraftAttachment = withContext(Dispatchers.IO) {
    val resolver = app.contentResolver
    val name = resolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use { c -> check(c.moveToFirst()); c.getString(0) } ?: error("Unable to read filename")
    val digest = java.security.MessageDigest.getInstance("SHA-256")
    var size = 0L
    resolver.openInputStream(uri)?.use { input ->
        val buffer = ByteArray(262144)
        while(true) { val n=input.read(buffer); if(n<0)break; size+=n; require(size<=256L*1024*1024) { "Choose a file up to 256 MiB" }; digest.update(buffer,0,n) }
    } ?: error("Unable to open file")
    require(size>0) { "Choose a nonempty file" }
    val sha = digest.digest().joinToString("") { "%02x".format(it) }
    val prefs=app.getSharedPreferences("work-upload-resume",0)
    val key=api.origin+":"+sha+":"+name
    val saved=prefs.getString(key,null)
    val state=try { if(saved==null)error("New upload"); JSONObject(api.request("/v1/work/uploads/$saved")) }
        catch(e: Exception) { JSONObject(api.request("/v1/work/uploads","POST",JSONObject().put("name",name).put("size",size))) }
    val id=state.getString("id"); prefs.edit().putString(key,id).apply()
    var offset=state.getLong("received")
    resolver.openInputStream(uri)?.use { input ->
        var skip=offset
        while(skip>0) { val n=input.skip(skip); if(n>0)skip-=n else {check(input.read()>=0);skip--} }
        val buffer=ByteArray(262144)
        while(offset<size) {
            var count=0
            while(count<buffer.size && offset+count<size) {val n=input.read(buffer,count,minOf(buffer.size-count,(size-offset-count).toInt()));check(n>=0) {"File changed during upload"};count+=n}
            val body=JSONObject().put("offset",offset).put("data",Base64.encodeToString(buffer,0,count,Base64.NO_WRAP))
            var failure: Exception?=null
            for(attempt in 0..2) {try {api.request("/v1/work/uploads/$id","PUT",body);failure=null;break} catch(e: kotlinx.coroutines.CancellationException){throw e} catch(e:Exception){failure=e}}
            failure?.let {throw it}
            offset+=count; progress("Uploading $name: ${offset*100/size}%")
        }
    } ?: error("Unable to reopen file")
    val done=JSONObject(api.request("/v1/work/uploads/$id/finish","POST",JSONObject()))
    check(done.getString("sha256")==sha) {"The selected file changed; upload it again"}
    prefs.edit().remove(key).apply();progress("Uploaded $name")
    DraftAttachment(name,"",uploadId=id,uploadBytes=size)
}
