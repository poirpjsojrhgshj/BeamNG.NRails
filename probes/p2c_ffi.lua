local ffi = require('ffi')
local socket = require('socket')
local r = {}
local s = string.char(0,0,128,63, 0,0,0,64)  -- floats 1.0, 2.0
local f = ffi.new('float[?]', 2); ffi.copy(f, s, 8)
r.floatCopy = tostring(f[0])..','..tostring(f[1])
-- timing: 16 MiB string -> float array copy
local big = string.rep(s, 2*1024*1024)
local t0 = socket.gettime()
local n = #big/4
local fa = ffi.new('float[?]', n); ffi.copy(fa, big, #big)
r.copy16MiB_ms = (socket.gettime()-t0)*1000
r.check = fa[n-1]
-- uint32 header parse
local u = ffi.new('uint32_t[1]'); ffi.copy(u, string.char(1,2,0,0), 4); r.u32 = u[0]
return jsonEncode(r)
