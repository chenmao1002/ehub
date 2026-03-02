#include "web_config.h"
#include <WiFi.h>

// ═══════════════════════════════════════════════════════════════
// 内嵌 HTML 页面 (存储在 PROGMEM 中节省 RAM)
// ═══════════════════════════════════════════════════════════════
static const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EHUB WiFi 配置</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;color:#333;padding:16px}
.card{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.08)}
h1{font-size:20px;color:#1a73e8;margin-bottom:8px;text-align:center}
h2{font-size:16px;color:#555;margin-bottom:12px;border-bottom:1px solid #eee;padding-bottom:8px}
.info-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #f5f5f5}
.info-label{color:#888;font-size:14px}
.info-value{font-weight:500;font-size:14px}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.online{background:#34a853}
.offline{background:#ea4335}
label{display:block;font-size:14px;color:#666;margin:8px 0 4px}
input[type="text"],input[type="password"],select{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:14px;outline:none}
input:focus,select:focus{border-color:#1a73e8}
.btn{display:block;width:100%;padding:12px;border:none;border-radius:8px;font-size:15px;font-weight:500;cursor:pointer;margin-top:12px;transition:opacity .2s}
.btn-primary{background:#1a73e8;color:#fff}
.btn-scan{background:#34a853;color:#fff}
.btn-danger{background:#ea4335;color:#fff}
.btn-warn{background:#fbbc04;color:#333}
.btn:active{opacity:.7}
.msg{padding:10px;border-radius:8px;margin-top:8px;font-size:14px;display:none}
.msg-ok{background:#e6f4ea;color:#137333}
.msg-err{background:#fce8e6;color:#c5221f}
</style>
</head>
<body>
<h1>EHUB WiFi Bridge</h1>

<div class="card">
<h2>设备状态</h2>
<div class="info-row"><span class="info-label">WiFi 模式</span><span class="info-value" id="mode">--</span></div>
<div class="info-row"><span class="info-label">已连接 SSID</span><span class="info-value" id="ssid">--</span></div>
<div class="info-row"><span class="info-label">IP 地址</span><span class="info-value" id="ip">--</span></div>
<div class="info-row"><span class="info-label">信号强度</span><span class="info-value" id="rssi">--</span></div>
<div class="info-row"><span class="info-label">TCP 客户端</span><span class="info-value" id="tcp">--</span></div>
<div class="info-row"><span class="info-label">运行时间</span><span class="info-value" id="uptime">--</span></div>
<div class="info-row"><span class="info-label">固件版本</span><span class="info-value" id="ver">--</span></div>
</div>

<div class="card">
<h2>WiFi 配置</h2>
<label>SSID</label>
<select id="ssid_sel" onchange="document.getElementById('ssid_in').value=this.value">
<option value="">-- 手动输入或扫描选择 --</option>
</select>
<input type="text" id="ssid_in" placeholder="输入 WiFi 名称">
<label>密码</label>
<input type="password" id="pass_in" placeholder="输入 WiFi 密码">
<button class="btn btn-scan" onclick="doScan()">扫描周围 WiFi</button>
<button class="btn btn-primary" onclick="doSave()">保存并连接</button>
<div class="msg" id="msg"></div>
</div>

<div class="card">
<h2>系统操作</h2>
<button class="btn btn-warn" onclick="doReboot()">重启 ESP32</button>
<button class="btn btn-danger" onclick="doReset()">恢复出厂设置</button>
</div>

<script>
function $(id){return document.getElementById(id)}
function showMsg(ok,txt){var m=$('msg');m.className='msg '+(ok?'msg-ok':'msg-err');m.textContent=txt;m.style.display='block';setTimeout(()=>{m.style.display='none'},4000)}
function fmtUp(s){var h=Math.floor(s/3600),m=Math.floor((s%3600)/60),ss=s%60;return h+'h '+m+'m '+ss+'s'}

function refresh(){
 fetch('/api/status').then(r=>r.json()).then(d=>{
  $('mode').textContent=d.mode;
  $('ssid').textContent=d.ssid||'--';
  $('ip').textContent=d.ip;
  $('rssi').textContent=d.rssi!==0?d.rssi+' dBm':'N/A';
  $('tcp').innerHTML=d.tcp_client?'<span class="status-dot online"></span>已连接':'<span class="status-dot offline"></span>未连接';
  $('uptime').textContent=fmtUp(d.uptime);
  $('ver').textContent=d.version||'--';
 }).catch(()=>{});
}

function doScan(){
 $('ssid_sel').innerHTML='<option>扫描中...</option>';
 fetch('/api/scan').then(r=>r.json()).then(d=>{
  var sel=$('ssid_sel');sel.innerHTML='<option value="">-- 选择 WiFi --</option>';
  d.networks.forEach(n=>{
   var o=document.createElement('option');o.value=n.ssid;
   o.textContent=n.ssid+' ('+n.rssi+' dBm'+(n.enc?' 🔒':'')+')';
   sel.appendChild(o);
  });
 }).catch(()=>{$('ssid_sel').innerHTML='<option>扫描失败</option>'});
}

function doSave(){
 var s=$('ssid_in').value.trim(),p=$('pass_in').value;
 if(!s){showMsg(false,'请输入 SSID');return}
 fetch('/api/wifi',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:s,pass:p})})
 .then(r=>r.json()).then(d=>{
  if(d.ok)showMsg(true,'配置已保存，正在重连...');else showMsg(false,'保存失败');
  setTimeout(refresh,6000);
 }).catch(()=>showMsg(false,'请求失败'));
}

function doReboot(){if(confirm('确认重启 ESP32？'))fetch('/api/reboot',{method:'POST'}).then(()=>showMsg(true,'正在重启...')).catch(()=>{})}
function doReset(){if(confirm('确认恢复出厂设置？所有配置将被清除！'))fetch('/api/reset',{method:'POST'}).then(()=>showMsg(true,'正在恢复并重启...')).catch(()=>{})}

refresh();
setInterval(refresh,5000);
</script>
</body>
</html>
)rawliteral";

// ═══════════════════════════════════════════════════════════════
// WebConfig 实现
// ═══════════════════════════════════════════════════════════════
WebConfig::WebConfig()
    : _server(nullptr)
    , _wifiMgr(nullptr)
    , _tcpSrv(nullptr)
    , _startTime(0)
{
}

void WebConfig::begin(WiFiManager& wifiMgr, TCPBridgeServer& tcpSrv) {
    _wifiMgr   = &wifiMgr;
    _tcpSrv    = &tcpSrv;
    _startTime = millis();

    _server = new WebServer(WEB_PORT);

    _server->on("/",          HTTP_GET,  [this]() { handleRoot(); });
    _server->on("/api/status", HTTP_GET,  [this]() { handleApiStatus(); });
    _server->on("/api/wifi",   HTTP_POST, [this]() { handleApiWifi(); });
    _server->on("/api/scan",   HTTP_GET,  [this]() { handleApiScan(); });
    _server->on("/api/reset",  HTTP_POST, [this]() { handleApiReset(); });
    _server->on("/api/reboot", HTTP_POST, [this]() { handleApiReboot(); });
    _server->onNotFound([this]() { handleNotFound(); });

    _server->begin();
}

void WebConfig::loop() {
    if (_server) {
        _server->handleClient();
    }
}

// ─── 返回主页 ───
void WebConfig::handleRoot() {
    _server->send_P(200, "text/html", INDEX_HTML);
}

// ─── GET /api/status ───
void WebConfig::handleApiStatus() {
    String mode;
    uint8_t st = _wifiMgr->getStatus();
    if (st == 0x01) mode = "STA";
    else if (st == 0x02) mode = "AP";
    else mode = "Disconnected";

    unsigned long uptimeSec = (millis() - _startTime) / 1000;

    String json = "{";
    json += "\"mode\":\"" + mode + "\",";
    json += "\"ssid\":\"" + _wifiMgr->getSSID() + "\",";
    json += "\"ip\":\"" + _wifiMgr->getIP().toString() + "\",";
    json += "\"rssi\":" + String(_wifiMgr->getRSSI()) + ",";
    json += "\"tcp_client\":" + String(_tcpSrv->hasClient() ? "true" : "false") + ",";
    json += "\"uptime\":" + String(uptimeSec) + ",";
    json += "\"version\":\"" FW_VERSION "\"";
    json += "}";

    _server->send(200, "application/json", json);
}

// ─── POST /api/wifi ───
void WebConfig::handleApiWifi() {
    if (!_server->hasArg("plain")) {
        _server->send(400, "application/json", "{\"ok\":false,\"error\":\"no body\"}");
        return;
    }

    String body = _server->arg("plain");

    // 简单 JSON 解析（不引入 ArduinoJson，手动提取）
    String ssid, pass;

    int ssidIdx = body.indexOf("\"ssid\"");
    if (ssidIdx >= 0) {
        int colonIdx = body.indexOf(':', ssidIdx);
        int startQuote = body.indexOf('"', colonIdx + 1);
        int endQuote = body.indexOf('"', startQuote + 1);
        if (startQuote >= 0 && endQuote > startQuote) {
            ssid = body.substring(startQuote + 1, endQuote);
        }
    }

    int passIdx = body.indexOf("\"pass\"");
    if (passIdx >= 0) {
        int colonIdx = body.indexOf(':', passIdx);
        int startQuote = body.indexOf('"', colonIdx + 1);
        int endQuote = body.indexOf('"', startQuote + 1);
        if (startQuote >= 0 && endQuote > startQuote) {
            pass = body.substring(startQuote + 1, endQuote);
        }
    }

    if (ssid.length() == 0) {
        _server->send(400, "application/json", "{\"ok\":false,\"error\":\"empty ssid\"}");
        return;
    }

    bool ok = _wifiMgr->configure(ssid.c_str(), pass.c_str());
    if (ok) {
        _wifiMgr->saveConfig();
        _server->send(200, "application/json", "{\"ok\":true}");
        // 延迟后重连
        delay(500);
        _wifiMgr->reconnect();
    } else {
        _server->send(500, "application/json", "{\"ok\":false}");
    }
}

// ─── GET /api/scan ───
void WebConfig::handleApiScan() {
    int n = WiFi.scanNetworks();

    String json = "{\"networks\":[";
    for (int i = 0; i < n && i < 20; i++) {
        if (i > 0) json += ",";
        json += "{\"ssid\":\"" + WiFi.SSID(i) + "\",";
        json += "\"rssi\":" + String(WiFi.RSSI(i)) + ",";
        json += "\"enc\":" + String(WiFi.encryptionType(i) != WIFI_AUTH_OPEN ? "true" : "false") + "}";
    }
    json += "]}";

    WiFi.scanDelete();
    _server->send(200, "application/json", json);
}

// ─── POST /api/reset ───
void WebConfig::handleApiReset() {
    _server->send(200, "application/json", "{\"ok\":true}");
    delay(500);
    _wifiMgr->resetConfig();  // 内部会 ESP.restart()
}

// ─── POST /api/reboot ───
void WebConfig::handleApiReboot() {
    _server->send(200, "application/json", "{\"ok\":true}");
    delay(500);
    ESP.restart();
}

// ─── 404 ───
void WebConfig::handleNotFound() {
    _server->send(404, "text/plain", "Not Found");
}
