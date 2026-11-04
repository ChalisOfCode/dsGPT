package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

@Composable
fun ChatActions(chat: Chat, vm: ChatModel) {
    var menu by remember { mutableStateOf(false) }
    var rename by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    var filesOpen by remember { mutableStateOf(false) }
    var name by remember(chat.title) { mutableStateOf(chat.title) }
    var files by remember { mutableStateOf<List<AttachmentRecord>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var more by remember { mutableStateOf(false) }
    val scope=rememberCoroutineScope()
    fun load(offset:Int) {scope.launch {try {val batch=vm.chatFiles(chat.id,offset);files=if(offset==0)batch else files+batch;more=batch.size==100} catch(e:Exception){error=e.message}}}
    Box {
        IconButton(onClick={menu=true},modifier=Modifier.semantics {contentDescription="Actions for ${chat.title}"}) {Text("⋯")}
        DropdownMenu(expanded=menu,onDismissRequest={menu=false}) {
            DropdownMenuItem(text={Text("Rename")},onClick={menu=false;name=chat.title;rename=true})
            DropdownMenuItem(text={Text(if(chat.pinned)"Unpin" else "Pin")},onClick={menu=false;vm.patch(chat,pinned=!chat.pinned)})
            DropdownMenuItem(text={Text("Files")},onClick={menu=false;filesOpen=true;files=emptyList();error=null;load(0)})
            DropdownMenuItem(text={Text("Delete chat")},onClick={menu=false;deleting=true})
        }
    }
    if(rename) AlertDialog(onDismissRequest={rename=false},title={Text("Rename chat")},text={OutlinedTextField(name,{name=it.take(300)},label={Text("Chat name")})},confirmButton={TextButton(enabled=name.isNotBlank(),onClick={vm.patch(chat,title=name.trim());rename=false}){Text("Save")}},dismissButton={TextButton(onClick={rename=false}){Text("Cancel")}})
    if(deleting) AlertDialog(onDismissRequest={deleting=false},title={Text("Delete ${chat.title}?")},text={Text("Removes this chat, its messages and attached files from dsGPT. Saved memories and existing backups remain.")},confirmButton={TextButton(onClick={vm.deleteChat(chat);deleting=false}){Text("Delete chat")}},dismissButton={TextButton(onClick={deleting=false}){Text("Cancel")}})
    if(filesOpen) AlertDialog(onDismissRequest={filesOpen=false},title={Text("Files in ${chat.title}")},text={Column(Modifier.heightIn(max=440.dp).verticalScroll(rememberScrollState())) {
        if(files.isEmpty()&&error==null)Text("No attached files loaded.")
        files.forEach {file->TextButton(onClick={vm.showAttachment(file,chat.id);filesOpen=false}){Text(file.name)}}
        if(more)TextButton(onClick={load(files.size)}){Text("Load more")}
        error?.let{Text(it,color=MaterialTheme.colorScheme.error)}
    }},confirmButton={TextButton(onClick={filesOpen=false}){Text("Close")}})
}
