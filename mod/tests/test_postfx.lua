-- luajit mod/tests/test_postfx.lua  (no far depth-of-field blur in our level)
local T = dofile((arg[0]:match('^(.*)[/\\]') or '.') .. '/testlib.lua')
local P = require('beamngEarth/postfx')
local vars = { ['$DOFPostFx::BlurMin'] = 0.1, ['$DOFPostFx::BlurMax'] = 0.25, ['$DOFPostFx::FocusRangeMin'] = 0,
               ['$DOFPostFx::FocusRangeMax'] = 250, ['$DOFPostFx::BlurCurveNear'] = 0, ['$DOFPostFx::BlurCurveFar'] = 50 }
local a, b, c, d, e, f = P.focusParams(function(k) return vars[k] end, 0)
T.check(a == 0.1 and b == 0 and c == 0 and d == 250 and e == -0 and f == 50, 'the player\'s DOF, far blur 0')
local dof = { farBlurMax = 0.25 }
scenetree = { findObject = function(n) return n == 'DOFPostEffect' and dof or nil end }
VariableRegistry = { get = function(k) return vars[k] end }
os.clock = function() return 100 end
P.update(false)
T.check(dof.farBlurMax == 0.25, 'other levels: untouched')
P.update(true)
T.check(dof.farBlurMax == 0 and dof.nearBlurMax == 0.1, 'our level: far blur off, near blur kept')
T.done('test_postfx')
