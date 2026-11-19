window.MathJax = {
  tex: {inlineMath: [['\\(', '\\)']], displayMath: [['\\[', '\\]']], processEscapes: true},
  options: {ignoreHtmlClass: '.*|', processHtmlClass: 'arithmatex'},
  startup: {ready: () => {
    MathJax.startup.defaultReady();
    if (typeof document$ !== 'undefined') document$.subscribe(() => {
      MathJax.startup.promise.then(() => { MathJax.typesetClear(); return MathJax.typesetPromise(); });
    });
  }}
};
