const featureRoute = /^\/(workbench|audit|models)(?:\/|$)/.test(window.location.pathname)

function finishRouteTransition() {
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      document.documentElement.classList.remove('route-transition-pending')
    })
  })
}

if (featureRoute) {
  const root = document.querySelector('#app')
  root.replaceChildren()
  document.body.classList.add('feature-app-body')

  import('./app/main.jsx')
    .then(({ mountFeatureApp }) => {
      mountFeatureApp(root)
      finishRouteTransition()
    })
    .catch((error) => {
      console.error(error)
      root.textContent = 'Feature application failed to load.'
      finishRouteTransition()
    })
} else {
  import('./main.js')
}
