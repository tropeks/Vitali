/** Vitali Imagem — pinned configuration for OHIF Viewer 3.12.8. */
window.config = {
  name: 'vitali-imagem',
  routerBasename: '/visualizador/',
  extensions: [],
  modes: [],
  customizationService: {},
  showStudyList: false,
  maxNumberOfWebWorkers: 3,
  showWarningMessageForCrossOrigin: false,
  showCPUFallbackMessage: true,
  showLoadingIndicator: true,
  strictZSpacingForVolumeViewport: true,
  groupEnabledModesFirst: true,
  showErrorDetails: 'production',
  investigationalUseDialog: { option: 'never' },
  dangerouslyUseDynamicConfig: { enabled: false },
  maxNumRequests: { interaction: 100, thumbnail: 75, prefetch: 25 },
  whiteLabeling: {
    createLogoComponentFn: function (React) {
      return React.createElement(
        'div',
        {
          'aria-label': 'Vitali Imagem',
          style: {
            alignItems: 'center', color: '#f8fafc', display: 'flex',
            fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
            fontSize: '14px', fontWeight: 600, gap: '9px',
            letterSpacing: '-0.01em', whiteSpace: 'nowrap',
          },
        },
        React.createElement('img', {
          alt: '', src: '/visualizador/assets/vitali-logo.svg',
          style: { height: '32px', width: '32px' },
        }),
        React.createElement('span', null, 'Vitali Imagem')
      );
    },
  },
  defaultDataSourceName: 'vitali-imagem',
  dataSources: [{
    namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
    sourceName: 'vitali-imagem',
    configuration: {
      friendlyName: 'Vitali Imagem',
      name: 'vitali-imagem',
      wadoUriRoot: '/imagens-dicom',
      qidoRoot: '/imagens-dicom',
      wadoRoot: '/imagens-dicom',
      qidoSupportsIncludeField: false,
      supportsReject: false,
      supportsStow: false,
      imageRendering: 'wadors',
      thumbnailRendering: 'wadors',
      enableStudyLazyLoad: true,
      supportsFuzzyMatching: false,
      supportsWildcard: false,
      staticWado: true,
      singlepart: 'bulkdata,pdf,video',
      omitQuotationForMultipartRequest: true,
      bulkDataURI: { enabled: true, relativeResolution: 'studies' },
    },
  }],
  httpErrorHandler: function (error) {
    console.warn(error && error.status ? error.status : error);
  },
};
