// Vitali's white-label layer for the embedded medical image viewer.
// The PACS plugin injects its data source and router settings after this file;
// presentation-only options remain under Vitali's control.
window.config = {
  whiteLabeling: {
    createLogoComponentFn: function (React) {
      return React.createElement(
        'div',
        {
          'aria-label': 'Vitali Imagem',
          className: 'flex items-center gap-2 text-white',
          style: { fontSize: '18px', fontWeight: 700, letterSpacing: '-0.02em' },
        },
        React.createElement(
          'span',
          {
            'aria-hidden': 'true',
            style: {
              alignItems: 'center',
              background: '#16a34a',
              borderRadius: '8px',
              display: 'inline-flex',
              height: '30px',
              justifyContent: 'center',
              width: '30px',
            },
          },
          'V'
        ),
        React.createElement('span', {}, 'Vitali Imagem')
      );
    },
  },
};

// Keep the browser/iframe title product-facing even if the bundled viewer sets
// its upstream project name while bootstrapping.
(function keepVitaliTitle() {
  var title = 'Vitali Imagem';
  document.title = title;
  new MutationObserver(function () {
    if (document.title !== title) document.title = title;
  }).observe(document.querySelector('title') || document.head, {
    childList: true,
    characterData: true,
    subtree: true,
  });
})();
