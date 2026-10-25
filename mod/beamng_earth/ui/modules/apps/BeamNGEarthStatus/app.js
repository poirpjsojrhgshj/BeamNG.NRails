// BeamNG.Earth status bar as a UI app (lua/ge/extensions/beamngEarth/hudapps.lua): street | place, the loading line under it.
angular.module('beamng.apps')
.directive('beamngEarthStatus', [function () {
  return {
    template:
      '<div class="bngApp" style="width:100%;height:100%;background:transparent;box-shadow:none;overflow:visible;" layout="column" layout-align="start center">' +
        '<span ng-show="text && !hidden" style="background:rgba(10,12,16,0.62);color:#eef1f4;border-radius:4px;' +
        'padding:3px 12px;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;">{{ text }}</span>' +
        '<span ng-show="loading && !hidden" style="margin-top:3px;background:rgba(10,12,16,0.62);color:#eef1f4;border-radius:4px;' +
        'padding:3px 12px;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;">{{ loading }}</span>' +
      '</div>',
    replace: true,
    link: function (scope) {
      'use strict'
      scope.text = ''
      scope.loading = ''
      scope.hidden = false
      var hello = function (on) {
        bngApi.engineLua('if beamngEarth_core and beamngEarth_core.hudApp then beamngEarth_core.hudApp("status", ' + on + ') end')
      }
      scope.$on('BeamNGEarthHud', function (event, data) {
        scope.$evalAsync(function () {
          scope.text = (data && data.status) || ''
          scope.loading = (data && data.loading) || ''
          scope.hidden = !!(data && data.hidden)
        })
      })
      hello(true)
      var again = setInterval(function () { hello(true) }, 3000)   // (after a Lua reload the mod forgets the app)
      scope.$on('$destroy', function () { clearInterval(again); hello(false) })
    }
  }
}]);
