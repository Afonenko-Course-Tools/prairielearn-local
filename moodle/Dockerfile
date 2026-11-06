# Официальный PHP и фиксированный выпуск Moodle; локальные образы не нужны.
FROM php:8.4.27-apache-bookworm
ARG MOODLE_VERSION=5.3
ARG MOODLE_SHA256=7e5edf110555956571f40e42acffde0eb23681ebebd212a2fec0fe7d795dd511
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl util-linux libfreetype6-dev libicu-dev \
      libjpeg62-turbo-dev libpng-dev libpq-dev libxml2-dev libzip-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j2 exif gd intl pgsql pdo_pgsql soap zip \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --show-error --location --retry 3 \
      "https://download.moodle.org/download.php/direct/stable503/moodle-${MOODLE_VERSION}.tgz" \
      --output /tmp/moodle.tgz \
    && echo "${MOODLE_SHA256}  /tmp/moodle.tgz" | sha256sum --check --strict \
    && mkdir -p /var/www/moodle \
    && tar -xzf /tmp/moodle.tgz --strip-components=1 -C /var/www/moodle \
    && rm /tmp/moodle.tgz \
    && mkdir -p /var/moodledata \
    && chown www-data:www-data /var/moodledata
COPY moodle/apache.conf /etc/apache2/sites-available/000-default.conf
COPY moodle/php.ini /usr/local/etc/php/conf.d/moodle.ini
COPY moodle/config.php /var/www/moodle/config.php
COPY scripts/moodle-bootstrap.php /usr/local/lib/moodle-bootstrap.php
COPY moodle/entrypoint.sh /usr/local/bin/moodle-entrypoint
RUN chmod 755 /usr/local/bin/moodle-entrypoint
WORKDIR /var/www/moodle
ENTRYPOINT ["moodle-entrypoint"]
CMD ["apache2-foreground"]
