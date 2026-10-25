// BeamNG.Earth connection banner as a UI app (lua/ge/extensions/beamngEarth/hudapps.lua): shown only when the world
// server needs attention, coloured by how bad it is.
angular.module('beamng.apps')
.directive('beamngEarthBanner', [function () {
  var BACK = { info: 'rgba(30,60,110,0.85)', ok: 'rgba(30,100,60,0.85)', warn: 'rgba(140,95,10,0.9)', error: 'rgba(150,25,25,0.92)' }
  return {
    template:
      '<div class="bngApp" style="width:100%;height:100%;background:transparent;box-shadow:none;" layout="row" layout-align="center start">' +
        '<span ng-show="text && !hidden" ng-style="{background: back}" style="color:#fff;border-radius:4px;padding:4px 14px;' +
        'font-size:14px;white-space:pre-line;text-align:center;">{{ text }}</span>' +
      '</div>',
    replace: true,
    link: function (scope) {
      'use strict'
      scope.text = ''
      scope.hidden = false
      scope.back = BACK.info
      var hello = function (on) {
        bngApi.engineLua('if beamngEarth_core and beamngEarth_core.hudApp then beamngEarth_core.hudApp("banner", ' + on + ') end')
      }
      scope.$on('BeamNGEarthHud', function (event, data) {
        scope.$evalAsync(function () {
          scope.text = (data && data.banner) || ''
          scope.back = BACK[(data && data.bannerLevel) || 'info'] || BACK.info
          scope.hidden = !!(data && data.hidden)
        })
      })
      hello(true)
      var again = setInterval(function () { hello(true) }, 3000)
      scope.$on('$destroy', function () { clearInterval(again); hello(false) })
    }
  }
}]);
