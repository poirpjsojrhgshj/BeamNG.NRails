local socket = require('socket')
local res = {}
for _, n in ipairs({1024*1024, 16*1024*1024}) do
  local t0 = socket.gettime()
  local c = socket.tcp(); c:settimeout(5); assert(c:connect('127.0.0.1', 47613)); c:setoption('tcp-nodelay', true)
  c:send(tostring(n)..'\n')
  local hdr = c:receive(4)
  local ffi = require("ffi")
  local u = ffi.new("uint32_t[1]"); ffi.copy(u, hdr, 4); local len = u[0]
  local body = c:receive(len)
  c:close()
  local t1 = socket.gettime()
  local p = ffi.new("uint8_t[?]", #body); ffi.copy(p, body, #body)
  res[#res+1] = string.format('%d bytes in %.1f ms (%.0f MB/s), byte[0]=%d byte[255]=%d byte[256]=%d ok=%s',
    #body, (t1-t0)*1000, #body/(t1-t0)/1e6, p[0], p[255], p[256], tostring(#body==len))
end
return table.concat(res, '\n')
