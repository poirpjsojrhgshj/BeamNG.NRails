local r = {}
r.sandboxApi = type(Engine.Sandbox)
if Engine.Sandbox then
  for k,v in pairs(Engine.Sandbox) do r['sb_'..tostring(k)] = tostring(v) end
end
local ok, socket = pcall(require, 'socket')
r.socket = ok and 'ok' or tostring(socket)
if ok then
  local c = socket.tcp(); c:settimeout(2)
  local a,b = c:connect('example.com', 80); r.connectExample = tostring(a)..' / '..tostring(b); c:close()
  local c2 = socket.tcp(); c2:settimeout(2)
  local a2,b2 = c2:connect('93.184.215.14', 80); r.connectIP = tostring(a2)..' / '..tostring(b2); c2:close()
  local c3 = socket.tcp(); c3:settimeout(1)
  local a3,b3 = c3:connect('127.0.0.1', 1); r.connectLocalClosedPort = tostring(a3)..' / '..tostring(b3); c3:close()
end
local okf, ef = pcall(function() return require('ffi').load('libc.so.6') end); r.ffiLoad = tostring(okf)..' '..tostring(ef)
r.ioPopen = tostring(io and io.popen)
r.osExecute = tostring(os and os.execute)
r.jit = jit and jit.version or 'nil'
r.BNGWebWSServer = type(BNGWebWSServer)
r.FS_userPath = FS and FS.getUserPath and FS:getUserPath() or '?'
return jsonEncode(r)
