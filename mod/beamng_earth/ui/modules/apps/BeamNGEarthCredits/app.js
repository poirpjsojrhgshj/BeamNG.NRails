// BeamNG.Earth data credits as a UI app (lua/ge/extensions/beamngEarth/hudapps.lua): the sources around the player.
angular.module('beamng.apps')
.directive('beamngEarthCredits', [function () {
  return {
    template:
      // the text sits on the app's bottom edge and grows upward past its top: five or more lines (the far imagery's
      // credits) were clipped in a 64 px app (the user, 2026-10-16); unclip() opens the game's app host too
      '<div class="bngApp" style="width:100%;height:100%;background:transparent;box-shadow:none;overflow:visible;position:relative;">' +
        '<span ng-show="text && !hidden" style="position:absolute;left:0;bottom:0;max-width:100%;box-sizing:border-box;' +
        'background:rgba(10,12,16,0.45);color:rgba(238,241,244,0.85);border-radius:3px;' +
        'padding:2px 6px;font-size:11px;line-height:1.3;">{{ text }}</span>' +
      '</div>',
    replace: true,
    link: function (scope, element) {
      'use strict'
      // the game's host of this app (.ui-app-host) clips at the layout's height (saved per player, 4em by default
      // before 1.4.13): our host only, overflow visible, so the credits grow upward over the 3D view
      var unclip = function () {
        var el = element && element[0]
        var host = el && el.closest && el.closest('.ui-app-host')
        if (host && host.style.overflow !== 'visible') host.style.overflow = 'visible'
      }
      setTimeout(unclip, 0)
      scope.text = ''
      scope.hidden = false
      var hello = function (on) {
        bngApi.engineLua('if beamngEarth_core and beamngEarth_core.hudApp then beamngEarth_core.hudApp("credits", ' + on + ') end')
      }
      scope.$on('BeamNGEarthHud', function (event, data) {
        scope.$evalAsync(function () {
          scope.text = (data && data.credits) || ''
          scope.hidden = !!(data && data.hidden)
        })
      })
      hello(true)
      var again = setInterval(function () { hello(true); unclip() }, 3000)
      scope.$on('$destroy', function () { clearInterval(again); hello(false) })
    }
  }
}]);
