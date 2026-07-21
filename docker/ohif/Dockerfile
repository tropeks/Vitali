FROM ohif/app:v3.12.8@sha256:0feb993fdbfe5de31dafba97b3d8f7b63a3a7a4565f2554528d4bfa34927bd58

USER root
RUN mkdir -p /usr/share/nginx/html/visualizador \
    && find /usr/share/nginx/html -mindepth 1 -maxdepth 1 ! -name visualizador \
       -exec mv {} /usr/share/nginx/html/visualizador/ \;

COPY app-config.js index.html manifest.json vitali-theme.css NOTICE /usr/share/nginx/html/visualizador/
COPY assets/vitali-logo.svg /usr/share/nginx/html/visualizador/assets/vitali-logo.svg
RUN gzip -d -f /usr/share/nginx/html/visualizador/*.bundle*.js.gz \
    && sed -i 's#__webpack_require__\.p = "/";#__webpack_require__.p = "/visualizador/";#g' \
      /usr/share/nginx/html/visualizador/*.bundle*.js \
    && for file in /usr/share/nginx/html/visualizador/*.bundle*.js; do \
         gzip -9 -f "$file"; touch "$file"; \
       done \
    && gzip -d -f /usr/share/nginx/html/visualizador/*.css.gz \
    && sed -i 's#url(/#url(/visualizador/#g' \
      /usr/share/nginx/html/visualizador/*.css \
    && for file in /usr/share/nginx/html/visualizador/*.css; do \
         gzip -9 -f "$file"; touch "$file"; \
       done \
    && gzip -d -f \
      /usr/share/nginx/html/visualizador/init-service-worker.js.gz \
      /usr/share/nginx/html/visualizador/sw.js.gz \
    && sed -i "s#'url':'/#'url':'/visualizador/#g" \
      /usr/share/nginx/html/visualizador/sw.js \
    && sed -i "s#'sw.js'#'sw.js?v=3.12.8-vitali.1'#" \
      /usr/share/nginx/html/visualizador/init-service-worker.js \
    && for file in \
         /usr/share/nginx/html/visualizador/init-service-worker.js \
         /usr/share/nginx/html/visualizador/sw.js; do \
         gzip -9 -f "$file"; touch "$file"; \
       done \
    && chown -R nginx:nginx /usr/share/nginx/html/visualizador

USER nginx
ENV PUBLIC_URL=/visualizador/ PORT=8080
EXPOSE 8080
