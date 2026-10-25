local ffi = require('ffi')
local r = {}
local keys = {}
for k,v in pairs(ffi) do keys[#keys+1]=k..'='..type(v) end
table.sort(keys); r.ffiKeys = table.concat(keys, ',')
local s = string.char(0,1,255,97, 0,0,128,63) -- last 4 = float 1.0
local ok, e = pcall(function()
  local buf = ffi.new('uint8_t[?]', #s)
  ffi.copy(buf, s, #s)
  local f = ffi.cast('float*', buf + 4)
  return tostring(buf[2])..' float='..tostring(f[0])
end)
r.newCopyCast = tostring(ok)..' '..tostring(e)
local ok2, e2 = pcall(function() local u = ffi.cast('uintptr_t', 5); return tostring(u) end)
r.castNumber = tostring(ok2)..' '..tostring(e2)
r.stringBuffer = tostring(pcall(require, 'string.buffer'))
return jsonEncode(r)
