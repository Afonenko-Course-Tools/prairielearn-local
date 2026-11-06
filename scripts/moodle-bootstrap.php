<?php
/** Первый запуск отдельной тестовой Moodle штатными CLI/API; повтор сохраняет её идентичность. */
function local_accounts(): array {
    $path = getenv('MOODLE_ACCOUNTS_FILE') ?: '/state/moodle-accounts.json';
    $accounts = json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    foreach (['admin', 'student', 'teacher'] as $kind) {
        if (empty($accounts[$kind]['username']) || empty($accounts[$kind]['password'])) {
            throw new RuntimeException('Отсутствует тестовая учётная запись: ' . $kind);
        }
    }
    if (count(array_unique(array_column($accounts, 'username'))) !== count($accounts)) {
        throw new RuntimeException('Имена тестовых пользователей должны различаться.');
    }
    return $accounts;
}


/** Разрешена только смена порта HTTPS; hostname, path и остальные части URL неизменны. */
function local_same_url_except_port(string $old, string $new): bool {
    $before = parse_url($old);
    $after = parse_url($new);
    if (!is_array($before) || !is_array($after) || ($before['scheme'] ?? '') !== 'https' ||
            ($after['scheme'] ?? '') !== 'https' || empty($before['host']) || empty($after['host']) ||
            isset($before['user']) || isset($before['pass']) || isset($after['user']) || isset($after['pass'])) {
        return false;
    }
    unset($before['port'], $after['port']);
    return $before === $after;
}

try {
    $accounts = local_accounts();
    if (in_array('--install', $argv, true)) {
        // До setup.php проверяем состояние БД без создания или изменения таблиц.
        $password = trim(file_get_contents(getenv('MOODLE_DB_PASSWORD_FILE') ?: '/state/moodle-db-password'));
        $dsn = 'pgsql:host=' . (getenv('MOODLE_DB_HOST') ?: 'moodle-db') .
            ';port=5432;dbname=' . (getenv('MOODLE_DB_NAME') ?: 'moodle');
        $pdo = new PDO($dsn, getenv('MOODLE_DB_USER') ?: 'moodle', $password, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
        $exists = $pdo->query("SELECT to_regclass('public.mdl_config') IS NOT NULL")->fetchColumn();
        if ($exists) {
            $version = $pdo->query("SELECT value FROM mdl_config WHERE name='version'")->fetchColumn();
            if (!$version) {
                throw new RuntimeException('Незавершённая установка Moodle: требуется восстановление БД, повторная установка запрещена.');
            }
            echo "Moodle уже установлена; БД и ключи сохранены.\n";
            exit(0);
        }
        // Параметры не передаются в командной строке ОС и не печатаются в журнале.
        $argv = ['install_database.php', '--agree-license', '--lang=en',
            '--adminuser=' . $accounts['admin']['username'], '--adminpass=' . $accounts['admin']['password'],
            '--adminemail=admin@example.invalid', '--fullname=Локальная Moodle', '--shortname=Local Moodle'];
        $_SERVER['argv'] = $argv;
        $_SERVER['argc'] = count($argv);
        require '/var/www/moodle/admin/cli/install_database.php';
        exit(0);
    }

    define('CLI_SCRIPT', true);
    require '/var/www/moodle/config.php';
    require_once $CFG->dirroot . '/course/lib.php';
    require_once $CFG->dirroot . '/course/modlib.php';
    require_once $CFG->dirroot . '/user/lib.php';
    require_once $CFG->dirroot . '/mod/lti/locallib.php';
    require_once $CFG->dirroot . '/mod/lti/lib.php';

    $admin = get_admin();
    if (!$admin || $admin->username !== $accounts['admin']['username']) {
        throw new RuntimeException('Администратор установленной Moodle не совпадает с локальным state.');
    }
    \core\session\manager::set_user($admin);
    $PAGE->set_context(context_system::instance());
    $transaction = $DB->start_delegated_transaction();
    set_config('noemailever', 1);
    set_config('smtphosts', '');

    $course = $DB->get_record('course', ['idnumber' => 'prairielearn-local']);
    if (!$course) {
        $category = $DB->get_record('course_categories', ['id' => 1], '*', MUST_EXIST);
        $course = create_course((object) [
            'category' => $category->id, 'shortname' => 'PrairieLearn Local',
            'fullname' => 'Локальная проверка PrairieLearn', 'idnumber' => 'prairielearn-local',
            'format' => 'topics', 'numsections' => 1, 'visible' => 1, 'enablecompletion' => 0,
            'startdate' => time() - 86400, 'enddate' => 0,
            'summary' => 'Тестовый курс без данных учреждения.', 'summaryformat' => FORMAT_HTML,
        ]);
    }
    $coursecontext = context_course::instance($course->id);
    $PAGE->set_context($coursecontext);
    $manual = enrol_get_plugin('manual');
    if (!$manual) {
        throw new RuntimeException('Не найден штатный manual enrolment plugin.');
    }
    $enrolment = $DB->get_record('enrol', ['courseid' => $course->id, 'enrol' => 'manual']);
    if (!$enrolment) {
        $enrolid = $manual->add_instance($course, ['status' => ENROL_INSTANCE_ENABLED]);
        $enrolment = $DB->get_record('enrol', ['id' => $enrolid], '*', MUST_EXIST);
    }
    $users = [];
    foreach (['student' => 'student', 'teacher' => 'editingteacher'] as $kind => $rolename) {
        $credentials = $accounts[$kind];
        $user = $DB->get_record('user', ['username' => $credentials['username'], 'mnethostid' => $CFG->mnet_localhost_id]);
        $marker = 'prairielearn-local-' . $kind;
        if (!$user) {
            $userid = \core\user::create_user((object) [
                'username' => $credentials['username'], 'password' => $credentials['password'],
                'auth' => 'manual', 'confirmed' => 1, 'mnethostid' => $CFG->mnet_localhost_id,
                'firstname' => 'Тестовый', 'lastname' => $kind === 'student' ? 'Студент' : 'Преподаватель',
                'email' => $kind . '@example.invalid', 'idnumber' => $marker, 'lang' => 'en',
            ]);
            $user = $DB->get_record('user', ['id' => $userid], '*', MUST_EXIST);
        }
        if ($user->idnumber !== $marker || $user->email !== $kind . '@example.invalid' || is_siteadmin($user)) {
            throw new RuntimeException('Обнаружен посторонний пользователь с тестовым именем.');
        }
        $role = $DB->get_record('role', ['shortname' => $rolename], '*', MUST_EXIST);
        if (!is_enrolled($coursecontext, $user, '', true)) {
            $manual->enrol_user($enrolment, $user->id, $role->id, 0, 0, ENROL_USER_ACTIVE);
        }
        $users[$kind] = $user;
    }

    $gateway = rtrim(getenv('GATEWAY_ORIGIN') ?: '', '/');
    $slug = getenv('GATEWAY_COURSE_SLUG') ?: 'example';
    if (!str_starts_with($gateway, 'https://') || !preg_match('/^[a-z0-9][a-z0-9-]*$/D', $slug)) {
        throw new RuntimeException('Неверные GATEWAY_ORIGIN или GATEWAY_COURSE_SLUG.');
    }
    $prefix = $gateway . '/gateway/courses/' . $slug;
    $target = $prefix . '/lti/launch';
    $initiate = $prefix . '/lti/login';
    $jwks = $prefix . '/.well-known/jwks.json';
    $typename = 'PrairieLearn Local';
    $type = $DB->get_record('lti_types', ['name' => $typename]);
    if (!$type) {
        $config = (object) [
            'lti_typename' => $typename, 'lti_description' => 'Тестовый вход в PrairieLearn без передачи оценок.',
            'lti_toolurl' => $target, 'lti_ltiversion' => LTI_VERSION_1P3,
            'lti_coursevisible' => LTI_COURSEVISIBLE_PRECONFIGURED, 'lti_keytype' => LTI_JWK_KEYSET,
            'lti_publickeyset' => $jwks, 'lti_initiatelogin' => $initiate, 'lti_redirectionuris' => $target,
            'lti_sendname' => LTI_SETTING_ALWAYS, 'lti_sendemailaddr' => LTI_SETTING_ALWAYS,
            'lti_acceptgrades' => LTI_SETTING_NEVER, 'lti_launchcontainer' => LTI_LAUNCH_CONTAINER_REPLACE_MOODLE_WINDOW,
            'lti_customparameters' => '', 'lti_contentitem' => 0,
            'ltiservice_gradesynchronization' => 0, 'ltiservice_memberships' => 0, 'ltiservice_toolsettings' => 0,
        ];
        $typeid = lti_add_type((object) ['state' => LTI_TOOL_STATE_CONFIGURED], $config);
        $type = lti_get_type($typeid);
    }
    $typeconfig = lti_get_type_config($type->id);
    $previousTarget = $type->baseurl;
    if ($type->ltiversion !== LTI_VERSION_1P3 || !local_same_url_except_port($previousTarget, $target) || empty($type->clientid) ||
            (int) $type->state !== LTI_TOOL_STATE_CONFIGURED) {
        throw new RuntimeException('Существующая LTI регистрация отличается; автоматическая перерегистрация запрещена.');
    }
    $previousPrefix = substr($previousTarget, 0, -strlen('/lti/launch'));
    foreach (['initiatelogin' => $previousPrefix . '/lti/login', 'publickeyset' => $previousPrefix . '/.well-known/jwks.json',
            'redirectionuris' => $previousTarget,
            'sendemailaddr' => (string) LTI_SETTING_ALWAYS, 'acceptgrades' => '0',
            'ltiservice_gradesynchronization' => '0'] as $key => $expected) {
        if ((string) ($typeconfig[$key] ?? '') !== $expected) {
            throw new RuntimeException('Изменилась настройка LTI: ' . $key);
        }
    }
    $activity = $DB->get_record('lti', ['course' => $course->id, 'name' => 'Открыть PrairieLearn']);
    if (!$activity) {
        $module = $DB->get_record('modules', ['name' => 'lti'], '*', MUST_EXIST);
        $info = add_moduleinfo((object) [
            'modulename' => 'lti', 'module' => $module->id, 'name' => 'Открыть PrairieLearn',
            'intro' => 'Список работ в PrairieLearn.', 'introformat' => FORMAT_HTML,
            'introeditor' => ['text' => '', 'format' => FORMAT_HTML, 'itemid' => 0],
            'typeid' => $type->id, 'toolurl' => $target, 'securetoolurl' => $target,
            'launchcontainer' => LTI_LAUNCH_CONTAINER_REPLACE_MOODLE_WINDOW,
            'instructorchoicesendname' => LTI_SETTING_ALWAYS, 'instructorchoicesendemailaddr' => LTI_SETTING_ALWAYS,
            'instructorchoiceacceptgrades' => LTI_SETTING_NEVER, 'grade' => 0, 'visible' => 1,
            'section' => 1, 'groupmode' => 0, 'groupingid' => 0, 'completion' => COMPLETION_DISABLED,
            'showdescription' => 1, 'showtitlelaunch' => 0, 'showdescriptionlaunch' => 0, 'debuglaunch' => 0,
        ], $course);
        $activity = $DB->get_record('lti', ['id' => $info->instance], '*', MUST_EXIST);
    }
    if ((int) $activity->typeid !== (int) $type->id || $activity->toolurl !== $previousTarget ||
            $activity->securetoolurl !== $previousTarget) {
        throw new RuntimeException('Существующий LTI activity относится к другой регистрации.');
    }
    $cm = get_coursemodule_from_instance('lti', $activity->id, $course->id, false, MUST_EXIST);
    $activity->cmid = $cm->id;
    $subjects = [];
    foreach ($users as $kind => $user) {
        \core\session\manager::set_user($user);
        $params = lti_build_request($activity, $typeconfig, $course, $type->id, false);
        $role = $kind === 'teacher' ? 'Instructor' : 'Learner';
        if ($params['roles'] !== $role || ($params['lis_person_contact_email_primary'] ?? '') !== $kind . '@example.invalid') {
            throw new RuntimeException('Роль или email тестового LTI launch не совпадают.');
        }
        $subjects[$kind] = (string) $params['user_id'];
    }
    \core\session\manager::set_user($admin);
    $platform = get_tool_type_config($type);
    $registration = [
        'registration' => [
            'issuer' => $platform['platformid'], 'clientId' => $platform['clientid'],
            'deploymentId' => (string) $platform['deploymentid'], 'contextId' => (string) $course->id,
            'authUrl' => $platform['authrequesturl'], 'tokenUrl' => $platform['accesstokenurl'],
            'jwksUrl' => $platform['publickeyseturl'],
            'activities' => ['catalog' => ['kind' => 'catalog', 'resourceLinkId' => (string) $activity->id]],
        ],
        'moodle' => ['courseId' => (int) $course->id, 'courseModuleId' => (int) $cm->id,
            'activityUrl' => $CFG->wwwroot . '/mod/lti/view.php?id=' . $cm->id],
        'syntheticSubjects' => $subjects,
    ];
    $output = getenv('MOODLE_REGISTRATION_FILE') ?: '/state/moodle/registration.json';
    $previous = null;
    if (file_exists($output)) {
        $previous = json_decode(file_get_contents($output), true, 512, JSON_THROW_ON_ERROR);
        $identity = $previous;
        foreach (['registration' => ['issuer', 'authUrl', 'tokenUrl', 'jwksUrl'], 'moodle' => ['activityUrl']] as $section => $fields) {
            foreach ($fields as $field) {
                $old = $previous[$section][$field] ?? null;
                $new = $registration[$section][$field];
                if (!is_string($old) || !local_same_url_except_port($old, $new)) {
                    throw new RuntimeException('Разрешена только смена порта URL своей тестовой Moodle.');
                }
                $identity[$section][$field] = $new;
            }
        }
        // Все native IDs, clientId, deploymentId и subjects обязаны совпасть.
        if ($identity !== $registration) {
            throw new RuntimeException('Регистрация не совпадает с сохранённой; локальный state не перезаписан.');
        }
    }
    if ($previousTarget !== $target) {
        if ($previous === null) {
            throw new RuntimeException('Для смены порта tool требуется сохранённая регистрация своей fixture.');
        }
        // Только URL-поля той же регистрации; DML/LTI API не пересоздают clientId и ключи.
        $DB->update_record('lti_types', (object) ['id' => $type->id, 'baseurl' => $target,
            'tooldomain' => lti_get_domain_from_url($target)]);
        foreach (['initiatelogin' => $initiate, 'publickeyset' => $jwks, 'redirectionuris' => $target] as $name => $value) {
            lti_update_config((object) ['typeid' => $type->id, 'name' => $name, 'value' => $value]);
        }
        $updated = clone $activity;
        $updated->instance = $activity->id;
        $updated->coursemodule = $cm->id;
        $updated->toolurl = $target;
        $updated->securetoolurl = $target;
        if (!lti_update_instance($updated, null)) {
            throw new RuntimeException('Не удалось обновить URL тестового LTI activity.');
        }
        rebuild_course_cache($course->id, true);
    }
    $transaction->allow_commit();
    if ($previous !== $registration) {
        $temp = $output . '.tmp';
        file_put_contents($temp, json_encode($registration, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR) . "\n");
        chmod($temp, 0644); // Только публичные идентификаторы, паролей и ключей здесь нет.
        rename($temp, $output);
    }
    echo "Moodle: тестовые пользователи и LTI регистрация готовы; прежние данные сохранены.\n";
} catch (Throwable $error) {
    // Moodle/драйвер могут включить credentials в exception: в журнале только класс ошибки.
    fwrite(STDERR, 'Ошибка инициализации Moodle (' . get_class($error) . "). Проверьте env, state и состояние БД.\n");
    exit(1);
}
