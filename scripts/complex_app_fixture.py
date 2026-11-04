"""Reviewed Task Ledger fixture and fixed behavior oracles; never model-generated.

The public domain API is intentionally shared by the independent model acceptance
contract. Native UI testing is a separate acceptance stage, not inferred here.
"""

# Embedded Kotlin and C++ retain natural formatting.
# ruff: noqa: E501
from dsgpt.app_builder import project_files

APP_TITLE = "Task Ledger"
DOMAIN_TEST_CASES = (
    "empty_counts", "trim_and_add", "invalid_title", "invalid_priority", "edit_preserves_identity",
    "toggle_counts", "remove_without_id_reuse", "ascii_search_title_and_notes", "status_filters",
    "unicode_roundtrip", "golden_persistence", "malformed_load_is_transactional", "duplicate_ids_rejected",
    "unsupported_version_rejected", "byte_limits", "unknown_id_rejected",
)
ORACLE_CASE_COUNT = len(DOMAIN_TEST_CASES)
FOLLOWUP_ORACLE_CASE_COUNT = ORACLE_CASE_COUNT + 2
GOLDEN = "DSGPT_TASK_LEDGER\t1\t3\n1\t1\t2\tQWxwaGE=\tbGluZTEKbGluZTI=\n2\t0\t0\t6Zuq\t\n"

KOTLIN_DOMAIN = r'''package @PACKAGE@

import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.util.Base64

data class Task(val id: Int, val title: String, val notes: String, val priority: Int, val done: Boolean)
data class LedgerCounts(val total: Int, val active: Int, val completed: Int)

class TaskLedger {
    private var tasks = mutableListOf<Task>()
    private var nextId = 1
    private fun checked(title: String, notes: String, priority: Int): String {
        val clean = title.trim(' ', '\t', '\r', '\n')
        require(clean.isNotEmpty() && clean.toByteArray(Charsets.UTF_8).size <= 240) { "Title must contain 1–240 UTF-8 bytes" }
        require(notes.toByteArray(Charsets.UTF_8).size <= 4096) { "Notes exceed 4096 UTF-8 bytes" }
        require(priority in 0..2) { "Priority must be 0, 1 or 2" }
        return clean
    }
    private fun asciiLower(text: String) = text.map { if (it in 'A'..'Z') it.lowercaseChar() else it }.joinToString("")
    fun add(title: String, notes: String = "", priority: Int = 1): Task {
        val clean = checked(title, notes, priority)
        require(nextId < Int.MAX_VALUE) { "Task IDs exhausted" }
        return Task(nextId++, clean, notes, priority, false).also { tasks.add(it) }
    }
    fun edit(id: Int, title: String, notes: String, priority: Int): Task {
        val clean = checked(title, notes, priority)
        val index = tasks.indexOfFirst { it.id == id }
        require(index >= 0) { "Select an existing task" }
        return tasks[index].copy(title = clean, notes = notes, priority = priority).also { tasks[index] = it }
    }
    fun toggle(id: Int): Task {
        val index = tasks.indexOfFirst { it.id == id }
        require(index >= 0) { "Select an existing task" }
        return tasks[index].copy(done = !tasks[index].done).also { tasks[index] = it }
    }
    fun remove(id: Int): Boolean = tasks.removeAll { it.id == id }
    fun visible(query: String = "", filter: String = "all"): List<Task> {
        require(filter in listOf("all", "active", "done")) { "Unknown filter" }
        val needle = asciiLower(query)
        return tasks.filter { task ->
            (filter == "all" || (filter == "done") == task.done) &&
                (asciiLower(task.title).contains(needle) || asciiLower(task.notes).contains(needle))
        }.toList()
    }
    fun counts(): LedgerCounts = LedgerCounts(tasks.size, tasks.count { !it.done }, tasks.count { it.done })
    private fun encode(text: String) = Base64.getEncoder().encodeToString(text.toByteArray(Charsets.UTF_8))
    private fun decode(text: String): String {
        val bytes = Base64.getDecoder().decode(text)
        require(Base64.getEncoder().encodeToString(bytes) == text) { "Invalid base64" }
        return try { Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString() }
            catch (problem: java.nio.charset.CharacterCodingException) { throw IllegalArgumentException("Invalid UTF-8", problem) }
    }
    fun serialize(): String = buildString {
        append("DSGPT_TASK_LEDGER\t1\t$nextId\n")
        tasks.forEach { append("${it.id}\t${if (it.done) 1 else 0}\t${it.priority}\t${encode(it.title)}\t${encode(it.notes)}\n") }
    }
    fun load(text: String) {
        val lines = text.split('\n').toMutableList()
        if (lines.lastOrNull() == "") lines.removeAt(lines.lastIndex)
        require(lines.isNotEmpty()) { "Missing persistence header" }
        val header = lines.removeAt(0).removeSuffix("\r").split('\t')
        require(header.size == 3 && header[0] == "DSGPT_TASK_LEDGER" && header[1] == "1") { "Unsupported persistence version" }
        fun positive(value: String): Int {
            require(value.isNotEmpty() && value.all { it in '0'..'9' }) { "Invalid numeric field" }
            return (value.toIntOrNull() ?: throw IllegalArgumentException("Invalid numeric field")).also { require(it > 0) }
        }
        val next = positive(header[2])
        val seen = mutableSetOf<Int>()
        val parsed = lines.map { line ->
            val parts = line.removeSuffix("\r").split('\t')
            require(parts.size == 5) { "Malformed task row" }
            val id = positive(parts[0])
            require(id < next && seen.add(id)) { "Duplicate or invalid task ID" }
            require(parts[1] in listOf("0", "1") && parts[2] in listOf("0", "1", "2")) { "Invalid task state" }
            val title = decode(parts[3]); val notes = decode(parts[4]); val priority = parts[2].toInt()
            require(checked(title, notes, priority) == title) { "Unnormalized title" }
            Task(id, title, notes, priority, parts[1] == "1")
        }
        tasks = parsed.toMutableList()
        nextId = next
    }
}
'''

KOTLIN_TESTS = r'''import @PACKAGE@.TaskLedger
import org.junit.Assert.*
import org.junit.Test

class IndependentTaskLedgerAcceptance {
    private fun rejects(block: () -> Unit) { try { block(); fail("Expected invalid input to be rejected") } catch (_: IllegalArgumentException) {} }
    @Test fun emptyCounts() { val l=TaskLedger(); assertEquals(0,l.counts().total); assertEquals(0,l.counts().active); assertEquals(0,l.counts().completed) }
    @Test fun trimAndAdd() { val l=TaskLedger(); val t=l.add("  Alpha\t", "memo", 2); assertEquals(1,t.id); assertEquals("Alpha",t.title); assertEquals("memo",t.notes); assertFalse(t.done); assertEquals(2,t.priority) }
    @Test fun invalidTitle() { val l=TaskLedger(); rejects { l.add(" \t\n") }; assertEquals(0,l.counts().total); l.add("Keep"); rejects { l.edit(1," ","changed",2) }; assertEquals("Keep",l.visible()[0].title); assertEquals(2,l.add("Next").id) }
    @Test fun invalidPriority() { val l=TaskLedger(); rejects { l.add("A","",-1) }; rejects { l.add("A","",3) }; assertEquals(1,l.add("B").id) }
    @Test fun editPreservesIdentity() { val l=TaskLedger(); l.add("A"); l.toggle(1); val t=l.edit(1,"  B ","new",0); assertEquals(1,t.id); assertEquals("B",t.title); assertTrue(t.done); assertEquals("new",t.notes); assertEquals(1,l.counts().total) }
    @Test fun toggleCounts() { val l=TaskLedger(); l.add("A"); l.add("B"); l.toggle(1); assertEquals(1,l.counts().active); assertEquals(1,l.counts().completed); l.toggle(1); assertEquals(2,l.counts().active) }
    @Test fun removeWithoutReuse() { val l=TaskLedger(); l.add("A"); l.add("B"); assertTrue(l.remove(2)); assertFalse(l.remove(99)); assertEquals(3,l.add("C").id); assertEquals(listOf(1,3),l.visible().map { it.id }) }
    @Test fun asciiSearchTitleAndNotes() { val l=TaskLedger(); l.add("Alpha","one"); l.add("Beta","ALPHABET"); l.add("Other","zero"); assertEquals(listOf(1,2),l.visible("aLpHa").map { it.id }); assertEquals(0,l.visible("missing").size) }
    @Test fun statusFilters() { val l=TaskLedger(); l.add("A"); l.add("B"); l.toggle(2); assertEquals(listOf(1),l.visible("","active").map { it.id }); assertEquals(listOf(2),l.visible("","done").map { it.id }); rejects { l.visible("","unknown") } }
    @Test fun unicodeRoundtrip() { val l=TaskLedger(); l.add("雪 🏁 café","tabs\tnewlines\n日本語",2); val r=TaskLedger(); r.load(l.serialize()); assertEquals(l.visible(),r.visible()); assertEquals(1,r.visible("雪").size); assertEquals(2,r.add("Next").id) }
    @Test fun goldenPersistence() { val l=TaskLedger(); l.add("  Alpha  ","line1\nline2",2); l.toggle(1); l.add("雪","",0); val golden="DSGPT_TASK_LEDGER\t1\t3\n1\t1\t2\tQWxwaGE=\tbGluZTEKbGluZTI=\n2\t0\t0\t6Zuq\t\n"; assertEquals(golden,l.serialize()); val r=TaskLedger(); r.load(golden); assertEquals("雪",r.visible()[1].title); assertTrue(r.visible()[0].done) }
    @Test fun malformedLoadIsTransactional() { val l=TaskLedger(); l.add("Keep","safe",1); val before=l.serialize(); rejects { l.load("DSGPT_TASK_LEDGER\t1\t2\n1\t0\t1\t%%%\t\n") }; assertEquals(before,l.serialize()); rejects { l.load("DSGPT_TASK_LEDGER\t1\t2\n1\t7\t1\tQQ==\t\n") }; assertEquals(before,l.serialize()); rejects { l.load("DSGPT_TASK_LEDGER\t1\t2\n1\t0\t1\t/w==\t\n") }; assertEquals(before,l.serialize()) }
    @Test fun duplicateIdsRejected() { val l=TaskLedger(); rejects { l.load("DSGPT_TASK_LEDGER\t1\t3\n1\t0\t1\tQQ==\t\n1\t0\t1\tQg==\t\n") }; assertEquals(0,l.counts().total) }
    @Test fun unsupportedVersionRejected() { val l=TaskLedger(); l.add("Keep"); val before=l.serialize(); rejects { l.load("DSGPT_TASK_LEDGER\t2\t1\n") }; assertEquals(before,l.serialize()) }
    @Test fun byteLimits() { val l=TaskLedger(); assertEquals(1,l.add("雪".repeat(80)).id); rejects { l.add("雪".repeat(81)) }; rejects { l.add("A","x".repeat(4097)) }; assertEquals(2,l.add("B","x".repeat(4096)).id) }
    @Test fun unknownIdRejected() { val l=TaskLedger(); l.add("Keep"); rejects { l.edit(9,"B","",1) }; rejects { l.toggle(9) }; assertEquals("Keep",l.visible()[0].title) }
}
'''

KOTLIN_ACTIVITY = r'''package @PACKAGE@

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import java.io.File

class MainActivity : ComponentActivity() {
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val ledger = TaskLedger()
        val saved = File(filesDir,"ledger-v1.tsv")
        var loadError = ""
        if (saved.exists()) try { ledger.load(saved.readText(Charsets.UTF_8)) } catch (_: Exception) { loadError = "Saved data could not be read; it has been preserved." }
        setContent {
            var revision by remember { mutableIntStateOf(0) }
            var title by remember { mutableStateOf("") }; var notes by remember { mutableStateOf("") }
            var priority by remember { mutableStateOf("1") }; var query by remember { mutableStateOf("") }
            var filter by remember { mutableStateOf("all") }; var selected by remember { mutableIntStateOf(0) }
            var error by remember { mutableStateOf(loadError) }
            val tasks = remember(revision,query,filter) { ledger.visible(query,filter) }
            val counts = remember(revision) { ledger.counts() }
            fun change(block: () -> Unit) {
                val before=ledger.serialize()
                try {
                    check(loadError.isEmpty()) { "Recover the preserved saved data before making changes" }
                    block()
                    val temp=File(filesDir,"ledger-v1.tmp")
                    temp.writeText(ledger.serialize(),Charsets.UTF_8)
                    check(temp.renameTo(saved)) { "Could not save changes" }
                    error=""; revision++
                } catch (problem: Exception) { ledger.load(before); error=problem.message ?: "Change failed"; revision++ }
            }
            MaterialTheme {
                Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement=Arrangement.spacedBy(6.dp)) {
                    Text("Task Ledger",style=MaterialTheme.typography.headlineMedium)
                    OutlinedTextField(value=title,onValueChange={title=it},label={Text("Title")},singleLine=true,modifier=Modifier.fillMaxWidth().semantics { contentDescription="Title" })
                    OutlinedTextField(value=notes,onValueChange={notes=it},label={Text("Notes")},modifier=Modifier.fillMaxWidth().semantics { contentDescription="Notes" },maxLines=3)
                    OutlinedTextField(value=priority,onValueChange={priority=it},label={Text("Priority")},singleLine=true,modifier=Modifier.fillMaxWidth().semantics { contentDescription="Priority" })
                    Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        Button(onClick={ change { selected=ledger.add(title,notes,priority.toIntOrNull() ?: -1).id } }) { Text("Add") }
                        Button(onClick={ change { ledger.edit(selected,title,notes,priority.toIntOrNull() ?: -1) } }) { Text("Save edit") }
                    }
                    Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        Button(onClick={ change { ledger.toggle(selected) } }) { Text("Toggle done") }
                        Button(onClick={ change { check(ledger.remove(selected)) { "Select an existing task" }; selected=0 } }) { Text("Delete") }
                    }
                    OutlinedTextField(value=query,onValueChange={query=it},label={Text("Search")},singleLine=true,modifier=Modifier.fillMaxWidth().semantics { contentDescription="Search" })
                    Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        listOf("All" to "all","Active" to "active","Done" to "done").forEach { (label,value) -> TextButton(onClick={filter=value}) { Text(label) } }
                    }
                    Text("Total: ${counts.total} | Active: ${counts.active} | Done: ${counts.completed}")
                    if(error.isNotEmpty()) Text(error,color=MaterialTheme.colorScheme.error)
                    tasks.forEach { task ->
                        TextButton(onClick={selected=task.id;title=task.title;notes=task.notes;priority=task.priority.toString()},modifier=Modifier.fillMaxWidth()) {
                            Text("#${task.id} ${task.title} | Priority ${task.priority} | ${if(task.done) "Done" else "Active"}")
                        }
                    }
                    if(tasks.isEmpty()) Text("No matching tasks")
                }
            }
        }
    }
}
'''

CPP_DOMAIN = r'''#pragma once
#include <algorithm>
#include <climits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace ledger {
struct Task { int id; std::string title; std::string notes; int priority; bool done; };
struct LedgerCounts { int total; int active; int completed; };
class TaskLedger {
    std::vector<Task> tasks_;
    int next_ = 1;
    static void check(bool valid,const char* message) { if(!valid) throw std::invalid_argument(message); }
    static bool utf8(const std::string& value) {
        for(std::size_t i=0;i<value.size();) {
            unsigned char c=value[i++]; if(c<128) continue;
            int n=0; unsigned code=0,minimum=0;
            if(c>=0xc2 && c<=0xdf) {n=1;code=c&31;minimum=0x80;}
            else if(c>=0xe0 && c<=0xef) {n=2;code=c&15;minimum=0x800;}
            else if(c>=0xf0 && c<=0xf4) {n=3;code=c&7;minimum=0x10000;}
            else return false;
            if(i+static_cast<std::size_t>(n)>value.size()) return false;
            while(n--) { unsigned char d=value[i++]; if((d&0xc0)!=0x80) return false; code=(code<<6)|(d&63); }
            if(code<minimum || code>0x10ffff || (code>=0xd800 && code<=0xdfff)) return false;
        }
        return true;
    }
    static std::string trim(const std::string& s) { auto first=s.find_first_not_of(" \t\r\n"); if(first==std::string::npos) return ""; return s.substr(first,s.find_last_not_of(" \t\r\n")-first+1); }
    static std::string checked(const std::string& title,const std::string& notes,int priority) {
        auto clean=trim(title); check(!clean.empty() && clean.size()<=240 && utf8(clean),"Title must contain 1-240 UTF-8 bytes");
        check(notes.size()<=4096 && utf8(notes),"Notes exceed 4096 UTF-8 bytes or are invalid"); check(priority>=0 && priority<=2,"Priority must be 0, 1 or 2"); return clean;
    }
    static std::string lower(std::string s) { for(char& c:s) if(c>='A' && c<='Z') c=static_cast<char>(c-'A'+'a'); return s; }
    static std::string encode(const std::string& value) {
        static const char* alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        std::string result; unsigned bits=0; int count=0;
        for(unsigned char c:value) { bits=(bits<<8)|c; count+=8; while(count>=6) {count-=6;result+=alphabet[(bits>>count)&63];} }
        if(count) result+=alphabet[(bits<<(6-count))&63]; while(result.size()%4) result+='='; return result;
    }
    static std::string decode(const std::string& value) {
        const std::string alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        check(value.size()%4==0,"Invalid base64"); std::string result; unsigned bits=0; int count=0; bool padding=false;
        for(char c:value) { if(c=='=') {padding=true;continue;} check(!padding,"Invalid base64"); auto at=alphabet.find(c); check(at!=std::string::npos,"Invalid base64"); bits=(bits<<6)|static_cast<unsigned>(at);count+=6;if(count>=8){count-=8;result+=static_cast<char>((bits>>count)&255);} }
        check(encode(result)==value && utf8(result),"Invalid base64 or UTF-8"); return result;
    }
    static std::vector<std::string> split(const std::string& value,char separator) {
        std::vector<std::string> result; std::size_t start=0;
        while(true) {auto end=value.find(separator,start);result.push_back(value.substr(start,end==std::string::npos?end:end-start));if(end==std::string::npos)break;start=end+1;} return result;
    }
    static int positive(const std::string& text) { check(!text.empty(),"Invalid numeric field"); long long n=0; for(char c:text) {check(c>='0' && c<='9',"Invalid numeric field");n=n*10+c-'0';check(n<=INT_MAX,"Invalid numeric field");}check(n>0,"Invalid numeric field");return static_cast<int>(n); }
    std::vector<Task>::iterator find(int id) {auto it=std::find_if(tasks_.begin(),tasks_.end(),[id](const Task& t){return t.id==id;});check(it!=tasks_.end(),"Select an existing task");return it;}
public:
    Task add(const std::string& title,const std::string& notes="",int priority=1) {auto clean=checked(title,notes,priority);check(next_<INT_MAX,"Task IDs exhausted");Task t{next_++,clean,notes,priority,false};tasks_.push_back(t);return t;}
    Task edit(int id,const std::string& title,const std::string& notes,int priority) {auto clean=checked(title,notes,priority);auto it=find(id);it->title=clean;it->notes=notes;it->priority=priority;return *it;}
    Task toggle(int id) {auto it=find(id);it->done=!it->done;return *it;}
    bool remove(int id) {auto it=std::find_if(tasks_.begin(),tasks_.end(),[id](const Task& t){return t.id==id;});if(it==tasks_.end())return false;tasks_.erase(it);return true;}
    std::vector<Task> visible(const std::string& query="",const std::string& filter="all") const {check(filter=="all" || filter=="active" || filter=="done","Unknown filter");std::vector<Task> result;auto needle=lower(query);for(const auto& t:tasks_)if((filter=="all" || (filter=="done")==t.done) && (lower(t.title).find(needle)!=std::string::npos || lower(t.notes).find(needle)!=std::string::npos))result.push_back(t);return result;}
    LedgerCounts counts() const {int done=0;for(const auto& t:tasks_)if(t.done)++done;return {static_cast<int>(tasks_.size()),static_cast<int>(tasks_.size())-done,done};}
    std::string serialize() const {std::ostringstream out;out<<"DSGPT_TASK_LEDGER\t1\t"<<next_<<'\n';for(const auto& t:tasks_)out<<t.id<<'\t'<<(t.done?1:0)<<'\t'<<t.priority<<'\t'<<encode(t.title)<<'\t'<<encode(t.notes)<<'\n';return out.str();}
    void load(const std::string& text) {
        auto lines=split(text,'\n');if(!lines.empty() && lines.back().empty())lines.pop_back();check(!lines.empty(),"Missing persistence header");
        for(auto& line:lines)if(!line.empty() && line.back()=='\r')line.pop_back();auto header=split(lines[0],'\t');check(header.size()==3 && header[0]=="DSGPT_TASK_LEDGER" && header[1]=="1","Unsupported persistence version");int next=positive(header[2]);std::set<int> seen;std::vector<Task> parsed;
        for(std::size_t i=1;i<lines.size();++i){auto p=split(lines[i],'\t');check(p.size()==5,"Malformed task row");int id=positive(p[0]);check(id<next && seen.insert(id).second,"Duplicate or invalid task ID");check(p[1]=="0" || p[1]=="1","Invalid task state");check(p[2]=="0" || p[2]=="1" || p[2]=="2","Invalid priority");auto title=decode(p[3]),notes=decode(p[4]);int priority=p[2][0]-'0';check(checked(title,notes,priority)==title,"Unnormalized title");parsed.push_back({id,title,notes,priority,p[1]=="1"});}
        tasks_=parsed;next_=next;
    }
};
}
'''

CPP_TESTS = r'''#include "task_ledger.h"
#include <functional>
#include <iostream>
#include <stdexcept>
using ledger::TaskLedger;
static void expect(bool value) { if(!value) throw std::runtime_error("Contract assertion failed"); }
static void rejects(const std::function<void()>& action) {bool rejected=false;try{action();}catch(const std::invalid_argument&){rejected=true;}expect(rejected);}
static std::vector<int> ids(const std::vector<ledger::Task>& tasks) {std::vector<int> result;for(const auto& t:tasks)result.push_back(t.id);return result;}
int main() {
    int passed=0;
    {TaskLedger l;expect(l.counts().total==0 && l.counts().active==0 && l.counts().completed==0);++passed;}
    {TaskLedger l;auto t=l.add("  Alpha\t","memo",2);expect(t.id==1 && t.title=="Alpha" && t.notes=="memo" && !t.done && t.priority==2);++passed;}
    {TaskLedger l;rejects([&]{l.add(" \t\n");});expect(l.counts().total==0);l.add("Keep");rejects([&]{l.edit(1," ","changed",2);});expect(l.visible()[0].title=="Keep" && l.add("Next").id==2);++passed;}
    {TaskLedger l;rejects([&]{l.add("A","",-1);});rejects([&]{l.add("A","",3);});expect(l.add("B").id==1);++passed;}
    {TaskLedger l;l.add("A");l.toggle(1);auto t=l.edit(1,"  B ","new",0);expect(t.id==1 && t.title=="B" && t.done && t.notes=="new" && l.counts().total==1);++passed;}
    {TaskLedger l;l.add("A");l.add("B");l.toggle(1);expect(l.counts().active==1 && l.counts().completed==1);l.toggle(1);expect(l.counts().active==2);++passed;}
    {TaskLedger l;l.add("A");l.add("B");expect(l.remove(2) && !l.remove(99));expect(l.add("C").id==3);expect(ids(l.visible())==std::vector<int>({1,3}));++passed;}
    {TaskLedger l;l.add("Alpha","one");l.add("Beta","ALPHABET");l.add("Other","zero");expect(ids(l.visible("aLpHa"))==std::vector<int>({1,2}));expect(l.visible("missing").empty());++passed;}
    {TaskLedger l;l.add("A");l.add("B");l.toggle(2);expect(ids(l.visible("","active"))==std::vector<int>({1}));expect(ids(l.visible("","done"))==std::vector<int>({2}));rejects([&]{l.visible("","unknown");});++passed;}
    {TaskLedger l;l.add(u8"雪 🏁 café",u8"tabs\tnewlines\n日本語",2);TaskLedger r;r.load(l.serialize());expect(r.serialize()==l.serialize());expect(r.visible(u8"雪").size()==1);expect(r.add("Next").id==2);++passed;}
    {TaskLedger l;l.add("  Alpha  ","line1\nline2",2);l.toggle(1);l.add(u8"雪","",0);std::string golden=u8"DSGPT_TASK_LEDGER\t1\t3\n1\t1\t2\tQWxwaGE=\tbGluZTEKbGluZTI=\n2\t0\t0\t6Zuq\t\n";expect(l.serialize()==golden);TaskLedger r;r.load(golden);expect(r.visible()[1].title==u8"雪" && r.visible()[0].done);++passed;}
    {TaskLedger l;l.add("Keep","safe",1);auto before=l.serialize();rejects([&]{l.load("DSGPT_TASK_LEDGER\t1\t2\n1\t0\t1\t%%%\t\n");});expect(l.serialize()==before);rejects([&]{l.load("DSGPT_TASK_LEDGER\t1\t2\n1\t7\t1\tQQ==\t\n");});expect(l.serialize()==before);rejects([&]{l.load("DSGPT_TASK_LEDGER\t1\t2\n1\t0\t1\t/w==\t\n");});expect(l.serialize()==before);++passed;}
    {TaskLedger l;rejects([&]{l.load("DSGPT_TASK_LEDGER\t1\t3\n1\t0\t1\tQQ==\t\n1\t0\t1\tQg==\t\n");});expect(l.counts().total==0);++passed;}
    {TaskLedger l;l.add("Keep");auto before=l.serialize();rejects([&]{l.load("DSGPT_TASK_LEDGER\t2\t1\n");});expect(l.serialize()==before);++passed;}
    {TaskLedger l;std::string title;for(int i=0;i<80;++i)title+=u8"雪";expect(l.add(title).id==1);rejects([&]{l.add(title+u8"雪");});rejects([&]{l.add("A",std::string(4097,'x'));});expect(l.add("B",std::string(4096,'x')).id==2);++passed;}
    {TaskLedger l;l.add("Keep");rejects([&]{l.edit(9,"B","",1);});rejects([&]{l.toggle(9);});expect(l.visible()[0].title=="Keep");++passed;}
    std::cout<<"DSGPT_TASK_LEDGER_TESTS="<<passed<<"\n";
    if(passed==16) std::cout<<"DSGPT_TASK_LEDGER_ORACLE_OK\n";
    return passed==16?0:1;
}
'''

CPP_MAIN = r'''#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shlobj.h>
#include <filesystem>
#include <fstream>
#include "task_ledger.h"

static ledger::TaskLedger ledgerState;
static HWND titleBox,notesBox,priorityBox,searchBox,filterBox,listBox,countLabel,errorLabel;
static bool changing=false, corruptSaved=false;
static int selected=0;
static std::filesystem::path dataPath;
static std::wstring wide(const std::string& text) {if(text.empty())return L"";int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),static_cast<int>(text.size()),nullptr,0);if(n<=0)throw std::invalid_argument("Invalid UTF-8");std::wstring r(n,L'\0');MultiByteToWideChar(CP_UTF8,0,text.data(),static_cast<int>(text.size()),r.data(),n);return r;}
static std::string utf8(const std::wstring& text) {if(text.empty())return "";int n=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,text.data(),static_cast<int>(text.size()),nullptr,0,nullptr,nullptr);if(n<=0)throw std::invalid_argument("Invalid text");std::string r(n,'\0');WideCharToMultiByte(CP_UTF8,0,text.data(),static_cast<int>(text.size()),r.data(),n,nullptr,nullptr);return r;}
static std::string value(HWND control) {int n=GetWindowTextLengthW(control);std::wstring s(static_cast<std::size_t>(n)+1,L'\0');GetWindowTextW(control,s.data(),n+1);s.resize(n);return utf8(s);}
static void put(HWND control,const std::string& text) {auto w=wide(text);SetWindowTextW(control,w.c_str());}
static void save() {auto tmp=dataPath;tmp+=L".tmp";{std::ofstream output(tmp,std::ios::binary|std::ios::trunc);if(!output)throw std::runtime_error("Cannot write saved data");output<<ledgerState.serialize();output.flush();if(!output)throw std::runtime_error("Cannot write saved data");}if(!MoveFileExW(tmp.c_str(),dataPath.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))throw std::runtime_error("Cannot replace saved data");}
static void refresh() {
    changing=true;SendMessageW(listBox,LB_RESETCONTENT,0,0);int mode=static_cast<int>(SendMessageW(filterBox,CB_GETCURSEL,0,0));std::string filter=mode==1?"active":mode==2?"done":"all";
    for(const auto& task:ledgerState.visible(value(searchBox),filter)) {auto text=wide("#"+std::to_string(task.id)+" "+task.title+" | Priority "+std::to_string(task.priority)+" | "+(task.done?"Done":"Active"));auto i=SendMessageW(listBox,LB_ADDSTRING,0,reinterpret_cast<LPARAM>(text.c_str()));SendMessageW(listBox,LB_SETITEMDATA,i,task.id);if(task.id==selected)SendMessageW(listBox,LB_SETCURSEL,i,0);}
    auto counts=ledgerState.counts();put(countLabel,"Total: "+std::to_string(counts.total)+" | Active: "+std::to_string(counts.active)+" | Done: "+std::to_string(counts.completed));changing=false;
}
static HWND control(HWND parent,const wchar_t* cls,const wchar_t* text,int id,int x,int y,int w,int h,DWORD style) {HWND c=CreateWindowExW(0,cls,text,WS_CHILD|WS_VISIBLE|style,x,y,w,h,parent,reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),GetModuleHandleW(nullptr),nullptr);SendMessageW(c,WM_SETFONT,reinterpret_cast<WPARAM>(GetStockObject(DEFAULT_GUI_FONT)),TRUE);return c;}
static void selectRow() {int i=static_cast<int>(SendMessageW(listBox,LB_GETCURSEL,0,0));if(i==LB_ERR)return;selected=static_cast<int>(SendMessageW(listBox,LB_GETITEMDATA,i,0));for(const auto& t:ledgerState.visible())if(t.id==selected){put(titleBox,t.title);put(notesBox,t.notes);put(priorityBox,std::to_string(t.priority));break;}}
static LRESULT CALLBACK WindowProcedure(HWND window,UINT message,WPARAM wparam,LPARAM lparam) {
    if(message==WM_CREATE) {
        control(window,L"STATIC",L"Title",0,12,12,90,24,0);titleBox=control(window,L"EDIT",L"",101,110,12,650,26,WS_BORDER|ES_AUTOHSCROLL);
        control(window,L"STATIC",L"Notes",0,12,48,90,24,0);notesBox=control(window,L"EDIT",L"",102,110,48,650,70,WS_BORDER|ES_MULTILINE|ES_AUTOVSCROLL|WS_VSCROLL);
        control(window,L"STATIC",L"Priority",0,12,128,90,24,0);priorityBox=control(window,L"EDIT",L"1",103,110,128,90,26,WS_BORDER|ES_AUTOHSCROLL);
        control(window,L"BUTTON",L"Add",201,12,168,150,30,BS_PUSHBUTTON);control(window,L"BUTTON",L"Save edit",202,174,168,150,30,BS_PUSHBUTTON);control(window,L"BUTTON",L"Toggle done",203,336,168,150,30,BS_PUSHBUTTON);control(window,L"BUTTON",L"Delete",204,498,168,150,30,BS_PUSHBUTTON);
        control(window,L"STATIC",L"Search",0,12,210,90,24,0);searchBox=control(window,L"EDIT",L"",104,110,210,450,26,WS_BORDER|ES_AUTOHSCROLL);filterBox=control(window,L"COMBOBOX",L"",105,575,210,185,120,CBS_DROPDOWNLIST|WS_VSCROLL);for(const auto* label:{L"All",L"Active",L"Done"})SendMessageW(filterBox,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(label));SendMessageW(filterBox,CB_SETCURSEL,0,0);
        countLabel=control(window,L"STATIC",L"",107,12,248,748,24,0);errorLabel=control(window,L"STATIC",L"",108,12,278,748,42,0);listBox=control(window,L"LISTBOX",L"",106,12,325,748,240,WS_BORDER|LBS_NOTIFY|WS_VSCROLL);
        if(corruptSaved)put(errorLabel,"Saved data could not be read; it has been preserved.");refresh();return 0;
    }
    if(message==WM_SIZE && listBox) {
        int width=LOWORD(lparam),height=HIWORD(lparam);int inputWidth=width-122;
        MoveWindow(titleBox,110,12,inputWidth,26,TRUE);MoveWindow(notesBox,110,48,inputWidth,70,TRUE);
        int buttonWidth=(width-48)/4;for(int i=0;i<4;++i)MoveWindow(GetDlgItem(window,201+i),12+i*(buttonWidth+8),168,buttonWidth,30,TRUE);
        MoveWindow(searchBox,110,210,width-322,26,TRUE);MoveWindow(filterBox,width-200,210,188,120,TRUE);
        MoveWindow(countLabel,12,248,width-24,24,TRUE);MoveWindow(errorLabel,12,278,width-24,42,TRUE);MoveWindow(listBox,12,325,width-24,height-337,TRUE);return 0;
    }
    if(message==WM_GETMINMAXINFO) {auto limits=reinterpret_cast<MINMAXINFO*>(lparam);limits->ptMinTrackSize.x=520;limits->ptMinTrackSize.y=480;return 0;}
    if(message==WM_COMMAND && !changing) {
        int id=LOWORD(wparam),event=HIWORD(wparam);
        if((id==104 && event==EN_CHANGE) || (id==105 && event==CBN_SELCHANGE)){refresh();return 0;}
        if(id==106 && event==LBN_SELCHANGE){selectRow();return 0;}
        if(id>=201 && id<=204 && event==BN_CLICKED) {
            auto before=ledgerState.serialize();
            try {
                if(corruptSaved)throw std::runtime_error("Recover the preserved saved data before making changes");
                auto p=value(priorityBox);int priority=p=="0"?0:p=="1"?1:p=="2"?2:-1;
                if(id==201)selected=ledgerState.add(value(titleBox),value(notesBox),priority).id;
                if(id==202)ledgerState.edit(selected,value(titleBox),value(notesBox),priority);
                if(id==203)ledgerState.toggle(selected);
                if(id==204){if(!ledgerState.remove(selected))throw std::invalid_argument("Select an existing task");selected=0;}
                save();put(errorLabel,"");
            }catch(const std::exception& e){ledgerState.load(before);put(errorLabel,e.what());}
            refresh();return 0;
        }
    }
    if(message==WM_DESTROY){PostQuitMessage(0);return 0;}
    return DefWindowProcW(window,message,wparam,lparam);
}
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE,PWSTR,int show) {
    try {
        wchar_t folder[32768];DWORD folderSize=GetEnvironmentVariableW(L"LOCALAPPDATA",folder,32768);if(folderSize==0 || folderSize>=32768)return 2;
        auto directory=std::filesystem::path(folder)/L"dsGPT-TaskLedger-@PROJECT@";std::filesystem::create_directories(directory);dataPath=directory/L"ledger-v1.tsv";
        if(std::filesystem::exists(dataPath)){try{std::ifstream input(dataPath,std::ios::binary);if(!input)throw std::runtime_error("Read failed");std::string saved((std::istreambuf_iterator<char>(input)),{});ledgerState.load(saved);}catch(...){corruptSaved=true;}}
        WNDCLASSW wc={};wc.lpfnWndProc=WindowProcedure;wc.hInstance=instance;wc.lpszClassName=L"dsGPTTaskLedgerWindow";wc.hCursor=LoadCursorW(nullptr,IDC_ARROW);wc.hbrBackground=reinterpret_cast<HBRUSH>(COLOR_WINDOW+1);RegisterClassW(&wc);
        HWND window=CreateWindowExW(0,wc.lpszClassName,L"Task Ledger",WS_OVERLAPPEDWINDOW,CW_USEDEFAULT,CW_USEDEFAULT,800,630,nullptr,nullptr,instance,nullptr);if(!window)return 1;ShowWindow(window,show);MSG msg;while(GetMessageW(&msg,nullptr,0,0)>0){TranslateMessage(&msg);DispatchMessageW(&msg);}return static_cast<int>(msg.wParam);
    } catch(...) {return 3;}
}
'''


def package_name(project_id):
    return "com.dsgpt.generated.p" + project_id.replace("-", "")


def independent_tests(project_id, followup=False):
    """Reviewer-written oracles, suitable for a copied model project with the contract API."""
    kotlin, cpp = KOTLIN_TESTS, CPP_TESTS
    if followup:
        cases = r'''    @Test fun clearCompletedPreservesActiveOrderAndIds() { val l=TaskLedger(); l.add("A"); l.add("B"); l.add("C"); l.toggle(1); l.toggle(3); assertEquals(2,l.clearCompleted()); assertEquals(listOf(2),l.visible().map { it.id }); assertEquals(4,l.add("D").id); assertEquals(0,l.clearCompleted()) }
    @Test fun clearCompletedRoundtrip() { val l=TaskLedger(); l.add("A"); l.add("B"); l.toggle(2); assertEquals(1,l.clearCompleted()); val r=TaskLedger(); r.load(l.serialize()); assertEquals(listOf(1),r.visible().map { it.id }); assertEquals(3,r.add("C").id); assertEquals(2,r.counts().active); val empty=TaskLedger(); assertEquals(0,empty.clearCompleted()); empty.add("Only"); empty.toggle(1); assertEquals(1,empty.clearCompleted()); assertEquals(0,empty.counts().total); assertEquals(2,empty.add("Next").id) }
'''
        kotlin = kotlin.rsplit("}", 1)[0] + cases + "}\n"
        extra = r'''    {TaskLedger l;l.add("A");l.add("B");l.add("C");l.toggle(1);l.toggle(3);expect(l.clearCompleted()==2);expect(ids(l.visible())==std::vector<int>({2}));expect(l.add("D").id==4);expect(l.clearCompleted()==0);++passed;}
    {TaskLedger l;l.add("A");l.add("B");l.toggle(2);expect(l.clearCompleted()==1);TaskLedger r;r.load(l.serialize());expect(ids(r.visible())==std::vector<int>({1}));expect(r.add("C").id==3 && r.counts().active==2);TaskLedger empty;expect(empty.clearCompleted()==0);empty.add("Only");empty.toggle(1);expect(empty.clearCompleted()==1 && empty.counts().total==0);expect(empty.add("Next").id==2);++passed;}
'''
        cpp = cpp.replace('    std::cout<<"DSGPT_TASK_LEDGER_TESTS=', extra + '    std::cout<<"DSGPT_TASK_LEDGER_TESTS=').replace("passed==16", "passed==18")
    return {
        "android/app/src/test/java/IndependentTaskLedgerAcceptance.kt": kotlin.replace("@PACKAGE@", package_name(project_id)),
        "windows/tests.cpp": cpp,
    }


def fixture(project_id, followup=False):
    package = package_name(project_id)
    android_root = "android/app/src/main/java/" + package.replace(".", "/")
    kotlin, activity, cpp, main = KOTLIN_DOMAIN, KOTLIN_ACTIVITY, CPP_DOMAIN, CPP_MAIN
    if followup:
        kotlin = kotlin.replace("    fun counts():", "    fun clearCompleted(): Int { val before=tasks.size; tasks.removeAll { it.done }; return before-tasks.size }\n    fun counts():")
        cpp = cpp.replace("    LedgerCounts counts()", "    int clearCompleted() {int before=static_cast<int>(tasks_.size());tasks_.erase(std::remove_if(tasks_.begin(),tasks_.end(),[](const Task& t){return t.done;}),tasks_.end());return before-static_cast<int>(tasks_.size());}\n    LedgerCounts counts()")
        activity = activity.replace('                    OutlinedTextField(value=query', '                    Button(onClick={ change { ledger.clearCompleted(); if(ledger.visible().none { it.id==selected }) selected=0 } }) { Text("Clear completed") }\n                    OutlinedTextField(value=query')
        main = main.replace('        countLabel=control', '        control(window,L"BUTTON",L"Clear completed",205,220,128,180,30,BS_PUSHBUTTON);\n        countLabel=control')
        main = main.replace("id<=204", "id<=205").replace('                save();put(errorLabel,"");', '                if(id==205){ledgerState.clearCompleted();bool exists=false;for(const auto& t:ledgerState.visible())if(t.id==selected)exists=true;if(!exists)selected=0;}\n                save();put(errorLabel,"");')
    files = {
        **project_files("android", APP_TITLE, project_id),
        **project_files("windows", APP_TITLE, project_id),
        android_root + "/TaskLedger.kt": kotlin.replace("@PACKAGE@", package),
        android_root + "/MainActivity.kt": activity.replace("@PACKAGE@", package),
        "windows/task_ledger.h": cpp,
        "windows/main.cpp": main.replace("@PROJECT@", project_id.replace("-", "")),
        **independent_tests(project_id, followup),
    }
    if followup:
        files["android/app/build.gradle"] = files["android/app/build.gradle"].replace("versionCode 1", "versionCode 2").replace("versionName '1.0'", "versionName '1.1'")
    return files
