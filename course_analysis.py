"""Evidence-based course outline reconstructed from the Telegram archive."""
from collections import Counter
from datetime import datetime


def _day(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')


def build(db):
    rows = list(db.execute("""
        SELECT m.sent_at, c.title, m.sender_name, COALESCE(m.text, m.caption, '') AS body
        FROM messages m JOIN chats c USING(chat_id)
        WHERE lower(COALESCE(m.sender_name, '')) LIKE '%sergey%'
        ORDER BY m.sent_at
    """))
    dates = [_day(r[0]) for r in rows]
    groups = Counter(r[1] for r in rows)
    return {
        'title': 'Восстановленная программа курса по переписке',
        'teacher': 'Сергей Васильев (Take Your Chance)',
        'method': 'Темы выведены из сообщений преподавателя; дата означает день, когда тема явно появилась в архиве. Бытовые и организационные сообщения исключены.',
        'coverage': {
            'firstTeacherMessage': min(dates) if dates else None,
            'lastTeacherMessage': max(dates) if dates else None,
            'teacherMessages': len(rows),
            'groupsUsed': sorted(groups),
        },
        'subjects': [
            {
                'id': 'mobile', 'title': 'Мобильная разработка',
                'groups': ['Мобильная 1094 разработка', '1092 разработка мобильных приложений', 'РМП 23/1093'],
                'outcome': 'Собрать и опубликовать рабочее приложение, подключить данные и довести проект до публикации.',
                'modules': [
                    {'dates': '10–17 марта 2026', 'title': 'Supabase и клиентское приложение', 'topics': ['создание проекта и таблиц Supabase', 'C#/.NET-клиент и инициализация', 'CRUD: регистрация и вход по имени/паролю', 'Supabase Auth и Storage', 'загрузка аватарки и файлов']},
                    {'dates': '19 марта – 6 апреля 2026', 'title': 'Git как рабочий процесс проекта', 'topics': ['clone, add, commit, push', 'Personal Access Token и GitHub', '.gitignore и защита .env', 'структура репозитория и код вместо архивов', 'проверка проектов и промежуточные результаты']},
                    {'dates': '2–18 сентября 2026', 'title': 'Flutter в облачной среде и веб-публикация', 'topics': ['DartPad, Zapp, GigaIDE/SberIDE', 'flutter run и web-server', 'flutter build web', 'base href и размещение результата в GitHub Pages/GitVerse Pages', 'проверка рабочей ссылки и коммитов']},
                    {'dates': '14–16 октября 2026', 'title': 'Сборка Android и публикация', 'topics': ['Android Studio и стандартный проект', 'flutter build apk и release-сборка', 'GitHub Actions для анализа и сборки', 'сохранение APK в Releases/артефактах', 'подготовка к ruStore и Google Play']},
                ],
            },
            {
                'id': 'security', 'title': 'Информационная безопасность',
                'groups': ['Информационная безопасность группа 3112', '26290911/3111 Инфбез'],
                'outcome': 'Безопасно работать с репозиториями, сетевыми ограничениями и публичным веб-кодом, понимая риски публикации секретов и ошибок.',
                'modules': [
                    {'dates': '3 сентября 2026', 'title': 'Среда разработки и публичный репозиторий', 'topics': ['VPN как способ доступа к недоступным ресурсам', 'регистрация и настройка GitHub', 'public-репозиторий и GitHub Pages', 'клонирование и публикация файлов']},
                    {'dates': '22 сентября – 1 октября 2026', 'title': 'Поиск данных в HTML', 'topics': ['классы, id и вложенность HTML', 'querySelectorAll и CSS-селекторы', 'поиск названия, даты и цены на публичных страницах', 'проверка ошибок в консоли браузера', 'обсуждение границ и надёжности найденных селекторов']},
                    {'dates': '9–12 октября 2026', 'title': 'GitHub и работа с токенами', 'topics': ['clone через терминал и VS Code', 'Personal Access Token classic', 'CSS/JavaScript в репозитории', 'автоматизация add/commit/push', 'разбор ошибок URL, ключей и пустых таблиц']},
                ],
            },
            {
                'id': 'ui', 'title': 'Пользовательские интерфейсы и веб-практика',
                'groups': ['МДК 01.01'],
                'outcome': 'Сверстать небольшой интерфейс, связать страницы, исследовать DOM и получить данные со страницы через JavaScript.',
                'modules': [
                    {'dates': '2–9 сентября 2026', 'title': 'HTML, GitHub Pages и связность проекта', 'topics': ['index.html и базовая структура HTML', 'имя репозитория username.github.io', 'ссылки между файлами и страницами', 'iframe и img', 'работа через терминал и Git']},
                    {'dates': '18–24 сентября 2026', 'title': 'Публикация Flutter и управление файлами', 'topics': ['GitVerse Pages', 'деплой Flutter Web', 'коммиты как след работы', 'списки ul/li и переходы между страницами', 'проверка результата по ссылке']},
                    {'dates': '29 сентября – 15 октября 2026', 'title': 'DOM, селекторы и мини-парсинг', 'topics': ['querySelectorAll и перебор for/foreach', 'поиск игровых карточек, новостей, фильмов и мероприятий', 'вывод найденных элементов через console.log', 'JSON.stringify и JSON.parse', 'исправление ошибок и проверка результата в консоли']},
                ],
            },
        ],
        'assessment': [
            'рабочая ссылка на опубликованный проект',
            'коммиты и понятная структура репозитория',
            'реальная проверка приложения или страницы',
            'объяснение найденной ошибки и выбранного селектора',
            'финальная сборка/публикация приложения',
        ],
    }
