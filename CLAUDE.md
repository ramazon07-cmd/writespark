# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Writespark is a Django 5.2 blog platform focused on the writing experience. It has a Tailwind dark-theme UI, post CRUD with auto-slug + auto read-time, categories with slug URLs, threaded comments with likes (rate-limited 5/min), a writers directory, search, and a custom S3 storage backend (Supabase) for media. Deployed to Vercel as a serverless Python app; production database is Neon PostgreSQL.

## Development Commands

```bash
# Activate venv
source venv/bin/activate

# Run dev server (SQLite when DATABASE_URL is unset)
python manage.py runserver

# Migrations
python manage.py migrate
python manage.py makemigrations

# Admin
python manage.py createsuperuser
python manage.py shell

# Tests (only the empty blog/tests.py exists today)
python manage.py test
python manage.py test blog.tests
```

## Project Structure

```
writespark/
├── blog/                       # Main app (verbose_name: "Writespark")
│   ├── models.py               # Category, Post, UserProfile, Comment
│   ├── views.py                # CBVs + add_comment FBV
│   ├── forms.py                # PostCreateForm, PostUpdateForm
│   ├── urls.py                 # namespace: blog
│   ├── admin.py                # Custom Post/Comment/Category/UserProfile/User admin
│   ├── storage.py              # MediaRootS3Storage (strips location prefix from S3 URLs)
│   └── templatetags/blog_extras.py  # time_ago, reading_time, tag_list, category_name
├── blog_project/
│   ├── settings.py             # env-driven config, Neon DB, S3 storage
│   ├── urls.py                 # /admin/, /accounts/, blog app
│   └── wsgi.py                 # Vercel entrypoint
├── templates/
│   ├── base.html               # Tailwind CDN + custom theme tokens (dark)
│   ├── blog/                   # home, post_list, post_detail, post_form, post_confirm_delete,
│   │                           #   dashboard, writers, category_posts
│   ├── components/             # navbar.html, footer.html
│   ├── registration/           # login.html, register.html
│   └── search.html             # Search results (top-level template)
├── static/
│   ├── css/                    # style.css (v1) + v2/ (current: base, blog_list, blog_detail, etc.)
│   ├── js/main.js
│   └── favicon.ico
├── media/                      # Local dev media (gitignored)
├── staticfiles/                # collectstatic output
├── vercel.json                 # Builds blog_project/wsgi.py via @vercel/python
├── build_files.sh              # pip install + collectstatic --noinput
├── requirements.txt
├── .env                        # local secrets (gitignored)
└── manage.py
```

## Application Logic

### Models (`blog/models.py`)

- **`Category`** — `name` (unique), `slug` (auto from name, unique+indexed), `description`, `created_at`. Ordered by name. `get_absolute_url` → `blog:category_posts`.
- **`Post`** — `title`, `slug` (auto, collision-safe), `author` (FK User, `related_name='blog_posts'`), `content`, `subtitle`, `image` (ImageField → `posts/`), `category` (FK, nullable, SET_NULL), `is_featured`, `read_time` (auto, 200 wpm), `tags` (comma-separated CharField, max 500), `status` (`draft`/`published`, default `draft`), timestamps. Ordered by `-created_at`. Composite indexes: `(status, -created_at)`, `(author, -created_at)`, `(category, -created_at)`, `(is_featured, -created_at)`.
- **`UserProfile`** — OneToOne to User, `avatar`, `role` (free text, e.g. "Senior Curator"), `bio`.
- **`Comment`** — FK Post (`related_name='comments'`), FK User, `content`, `parent` (self-FK, `related_name='replies'`, nullable for threading), `likes` (PositiveIntegerField counter), `created_at`. Ordered by `created_at`. Index `(post, -created_at)`.

### Views (`blog/views.py`)

- `HomeView(ListView)` — Empty main queryset; pulls `featured_posts` (up to 3 published+featured) and `recent_posts` (up to 6 published+non-featured) into context.
- `PostListView(ListView)` — `paginate_by=9`. Filters `status='published'`. Accepts GET `q` (search title/subtitle/content) and `category` (slug). `select_related('author', 'category')`.
- `PostDetailView(DetailView)` — `select_related` + `prefetch_related('comments')`; passes ordered `comments` and `all_categories` to template.
- `PostCreateView(LoginRequiredMixin, CreateView)` — `form_valid` forces `author=request.user` and `status='published'` (no draft-on-create from UI).
- `PostUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView)` — `get_queryset` filters to `author=request.user`; `test_func` re-checks `request.user == post.author`.
- `PostDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView)` — same author check.
- `UserDashboardView(LoginRequiredMixin, ListView)` — Author's own posts (paginated 9), ordered by `-created_at`; context has `drafts_count` and `published_count`.
- `WritersView(ListView)` — All published posts + `writers` context: Users annotated with `post_count` from `blog_posts`, ordered by `post_count` desc.
- `CategoryPostsView(ListView)` — `paginate_by=9`; stores `self.category` in `get_queryset`, exposes it and `all_categories` in context.
- `SearchView(ListView)` — `paginate_by=9`; renders `search.html` (top-level template, not `blog/search.html`). Same `q`+`category` filtering as `PostListView`.
- `RegisterView(CreateView)` — Uses Django's `UserCreationForm`; redirects to `login` on success.
- `add_comment(request, slug)` — FBV. `@login_required` + `@ratelimit(key='user', rate='5/m', method='POST', block=True)`. POST only; empty content → error message. Creates a top-level Comment (no parent wiring from this view — threading exists at the model level but is not exercised here).

### URL Routes (`blog/urls.py`, app namespace `blog`)

| Path | Name |
|---|---|
| `/` | `home` |
| `/posts/` | `post_list` |
| `/writers/` | `writers` |
| `/dashboard/` | `dashboard` |
| `/post/new/` | `post_create` |
| `/post/<slug>/` | `post_detail` |
| `/post/<slug>/edit/` | `post_update` |
| `/post/<slug>/delete/` | `post_delete` |
| `/post/<slug>/comment/` | `add_comment` |
| `/category/<slug>/` | `category_posts` |
| `/search/` | `search` |
| `/register/` | `register` |

Root `blog_project/urls.py` adds `/admin/`, mounts `blog.urls` at `/`, and `django.contrib.auth.urls` at `/accounts/`. Dev-only: `static()` helpers for `STATIC_URL`/`MEDIA_URL` when `DEBUG=True`.

### Forms (`blog/forms.py`)

- `PostCreateForm` — `fields = [title, subtitle, content, image, category, is_featured, tags]`. No `status` field (always published on create).
- `PostUpdateForm` — Same fields plus `status`. Heavy inline Tailwind widget classes (dark theme tokens) on every widget.

### Admin (`blog/admin.py`)

- `CategoryAdmin` — list shows `post_count`; `prepopulated_fields = {'slug': ('name',)}`.
- `UserProfileAdmin` — simple fieldsets.
- `PostAdmin` — `list_display` includes status/is_featured/read_time; `raw_id_fields = ['author']`; `date_hierarchy = 'created_at'`.
- `CommentAdmin` — `content_preview` truncates to 50 chars.
- `User` is unregistered and re-registered with `UserProfileInline` (Stacked) + `PostInline` (Tabular).

### Template Tags (`blog/templatetags/blog_extras.py`)

- `{{ value|time_ago }}` — "just now" if <60s, else "X ago" via `django.utils.timesince`.
- `{{ post|reading_time }}` — defensive version of the model save logic (200 wpm, `max(1, ...)`).
- `{{ tags_string|tag_list }}` — splits comma-separated tags into trimmed list.
- `{{ category|category_name }}` — `.name.upper()` or `'ARTICLE'`.

## Key Implementation Details

### Post Slugification (`Post.save()`)
- Only auto-generates when `slug` is blank.
- Loops with `type(self).objects.filter(slug=...).exclude(pk=self.pk)` so self-updates don't collide with themselves.
- Appends `-2`, `-3`, … until unique.

### Read Time (`Post.save()`)
- `words = len(self.content.split()) if self.content else 0`
- `read_time = max(1, words // 200)` — always at least 1, no upper cap.

### Access Control
- Create requires login (`LoginRequiredMixin`).
- Edit/Delete require login AND `request.user == post.author` (checked twice: queryset filter + `test_func`).

### Content Visibility
- Public listings: `status='published'` only (Home, List, Search, Category, Writers).
- Dashboard shows author's own posts of any status.
- `add_comment` looks up the post by slug with `Post.objects.get` (not `get_object_or_404`) and silently redirects to `post_list` if missing.

### Commenting
- `add_comment` is rate-limited to 5 POSTs/min per user (`django-ratelimit`, `block=True`).
- Always creates a top-level comment — no `parent` handling, so nested replies exist at the model level but the current view doesn't expose them.
- The model has `parent` and a `replies` reverse accessor; the `CommentAdmin` displays `parent`.

### Database Indexes
- Single-field: `Category.slug`, `Category.created_at`, `Post.slug`, `Post.author`, `Post.created_at`, `Post.status`, `Post.category`, `Post.is_featured`, `UserProfile.user`, `Comment.post`, `Comment.user`, `Comment.created_at`.
- Composite: `(status, -created_at)`, `(author, -created_at)`, `(category, -created_at)`, `(is_featured, -created_at)` on `Post`; `(post, -created_at)` on `Comment`.
- Migrations present: `0001_initial`, `0002_post_image`, `0003_category_comment_likes_comment_parent_and_more`, `0004_add_performance_indexes`, `0005_alter_post_slug`.

## Media Storage

`blog/storage.py` defines `MediaRootS3Storage(S3Boto3Storage)` used as Django's `default` storage (see `STORAGES` in settings). Two custom overrides fix a doubled-location bug on the Supabase/S3-compatible endpoint:

- `_save` strips a leading `media/` (or `AWS_LOCATION`) prefix before delegating to S3.
- `url` strips the same prefix when generating public URLs (works with `AWS_S3_CUSTOM_DOMAIN` so the rendered URL is e.g. `https://<custom-domain>/posts/foo.jpg` instead of `.../media/media/posts/foo.jpg`).

`AWS_QUERYSTRING_AUTH = False` so public bucket objects get plain unsigned URLs.

## Settings Highlights (`blog_project/settings.py`)

- Env-loaded via `python-dotenv`. `DEBUG` is parsed from the string `"True"`.
- Database: Neon PostgreSQL when `DATABASE_URL` is set (with `connect_timeout=10`); otherwise local SQLite at `BASE_DIR/db.sqlite3`.
- Templates: `DIRS=[BASE_DIR / "templates"]` plus app dirs.
- Static: `STATIC_URL=/static/`, `STATICFILES_DIRS=[static]`, `STATIC_ROOT=staticfiles/` (used by Vercel `collectstatic`).
- Auth redirects: `LOGIN_REDIRECT_URL="/"`, `LOGOUT_REDIRECT_URL="/"`.
- Security hardening when `DEBUG=False`: HSTS (1 year, includeSubDomains, preload), secure cookies, `X_FRAME_OPTIONS=DENY`, XSS/content-type filters.
- Cache: `LocMemCache` (not Redis) — process-local; fine for single-instance dev, would need swap for production scale.
- Logging: DB query logger is currently commented out.

## Deployment (Vercel)

- `vercel.json` builds `blog_project/wsgi.py` with `@vercel/python` and routes everything to the WSGI app.
- `build_files.sh` runs `pip install -r requirements.txt` then `python manage.py collectstatic --noinput`.
- `.env.example` not present; `.env` is gitignored — production env vars (DJANGO_SECRET_KEY, DATABASE_URL, AWS_* for Supabase S3, ALLOWED_HOSTS including `writespark.vercel.app`) are configured in the Vercel project settings.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DEBUG` | `False` | Must be the string `"True"` to enable debug |
| `DJANGO_SECRET_KEY` | insecure dev default | Override in production |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated; production adds `writespark.vercel.app` |
| `DATABASE_URL` | (unset) | When unset → SQLite at `db.sqlite3`; when set → `dj_database_url.parse(..., conn_max_age=0)` (Neon in prod) |
| `AWS_ACCESS_KEY_ID` | (unset) | Required for S3 storage |
| `AWS_SECRET_ACCESS_KEY` | (unset) | Required for S3 storage |
| `AWS_S3_ENDPOINT_URL` | (unset) | Supabase S3 endpoint in prod |
| `AWS_S3_REGION_NAME` | `us-east-1` | S3 region |
| `AWS_STORAGE_BUCKET_NAME` | (unset) | Bucket name |
| `AWS_S3_CUSTOM_DOMAIN` | (unset) | Public CDN domain for S3 URLs |
| `AWS_LOCATION` | `media` | Subfolder; storage class strips this prefix to avoid double prefixes |

## Gotchas / Things to Remember

- `PostCreateView` always sets `status='published'`. The `status` field is only editable via `PostUpdateForm` / admin.
- `SearchView` uses `templates/search.html` (top-level), not `templates/blog/search.html`. Don't move it.
- `add_comment` does not wire `parent` — threaded replies exist in the model/admin but aren't reachable from the current UI.
- `AWS_LOCATION` default `media` matches the `upload_to='posts/'` / `upload_to='avatars/'` paths. The storage class strips the `media/` prefix from saved keys and URLs to avoid `media/media/...` doubling (recently fixed — see commit `73a94ea`).
- `DEBUG` env var must be exactly the string `"True"`, not `1`/`true`/etc.
- `db.sqlite3`, `media/`, `staticfiles/`, `venv/`, `.env`, and `.vercel/` are gitignored. `staticfiles/` is regenerated by `collectstatic`.
- `tests.py` exists but is empty — no test coverage to lean on.
