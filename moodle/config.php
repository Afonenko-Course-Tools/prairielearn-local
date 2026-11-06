<?php
// Конфигурация контейнера; пароли читаются только из нового локального state.
unset($CFG);
$CFG = new stdClass();
$CFG->dbtype = 'pgsql';
$CFG->dblibrary = 'native';
$CFG->dbhost = getenv('MOODLE_DB_HOST') ?: 'moodle-db';
$CFG->dbname = getenv('MOODLE_DB_NAME') ?: 'moodle';
$CFG->dbuser = getenv('MOODLE_DB_USER') ?: 'moodle';
$passwordfile = getenv('MOODLE_DB_PASSWORD_FILE') ?: '/state/moodle-db-password';
if (!is_readable($passwordfile)) {
    throw new RuntimeException('Не найден файл пароля Moodle DB. Выполните init-config.');
}
$CFG->dbpass = trim(file_get_contents($passwordfile));
$CFG->prefix = 'mdl_';
$CFG->dboptions = ['dbpersist' => false, 'dbport' => 5432, 'dbsocket' => '', 'dbcollation' => ''];
$CFG->wwwroot = rtrim(getenv('MOODLE_WWWROOT') ?: '', '/');
if (!str_starts_with($CFG->wwwroot, 'https://')) {
    throw new RuntimeException('MOODLE_WWWROOT должен содержать публичный HTTPS URL.');
}
$CFG->dataroot = '/var/moodledata';
$CFG->admin = 'admin';
$CFG->directorypermissions = 02770;
$CFG->sslproxy = true;
$CFG->noemailever = true;
$CFG->smtphosts = '';
$CFG->debug = 0;
$CFG->debugdisplay = false;
// LTI обращается к внутренним адресам Compose; проверка TLS остаётся включённой.
$CFG->curlsecurityblockedhosts = '';
$CFG->curlsecurityallowedport = '';
require_once __DIR__ . '/public/lib/setup.php';
