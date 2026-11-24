# Front-end freeze manifest

This records the current Django front end and its backend data contract. The read-only reference at `_design_source/rendered_dashboard_enduser.html` is not a serving template and is not included in the app-asset scans.

## Template and static tree

Line counts are for the current files.

```text
templates/
  base.html (26)
  partials/
    field.html (10)
    mark.svg (4)
    messages.html (9)
    sidebar.html (45)
    topbar.html (15)
accounts/templates/accounts/
  access_denied.html (16)
  access_map.html (60)
  login.html (35)
  overview.html (26)
  password_change.html (33)
operations/templates/operations/
  dashboard.html (39)
  form_page.html (42)
  need_detail.html (60)
  records.html (27)
  partials/
    empty_state.html (7)
    metric_strip.html (9)
    module_tiles.html (22)
    queue_list.html (19)
    records_table.html (32)
    system_status.html (12)
static/
  css/main.css (195)
  js/app.js (41)
```

## Named route map

The project-authored routes are listed first. The Django admin names below are framework-generated routes included by `config/urls.py`; they are not SIA screens. “Unknown role” means an authenticated user whose groups contain no recognized SIA role.

| URL name | Path | View | Methods | Roles allowed / guard | Template or response | Authorized role | Unauthorized role | Anonymous |
|---|---|---|---|---|---|---|---|---|
| `dashboard` | `/` | `operations.views.dashboard` | GET | Recognized SIA role intended; currently `login_required` only, no role guard | `operations/dashboard.html` | 200 | 200 for unknown role (**unprotected-role defect**) | 302 to login |
| `form_page` | `/records/<module>/new/` | `operations.views.form_page` | GET, POST | `act` for the module | `operations/form_page.html` | 200 | 403 for read/no access | 302 to login |
| `need_detail` | `/records/<module>/<reference>/` | `operations.views.need_detail` | GET | `read` or `act` for the module | `operations/need_detail.html` | 200 | 403 for no access | 302 to login |
| `records` | `/records/<module>/` | `operations.views.records` | GET | `read` or `act` for the module | `operations/records.html` | 200 | 403 for no access | 302 to login |
| `login` | `/accounts/login/` | `accounts.views.ProjectLoginView` | GET, POST | Public sign-in endpoint | `accounts/login.html` | 302 if already authenticated | 302 if already authenticated | 200 |
| `access_map` | `/accounts/access/` | `accounts.views.access_map` | GET | Any authenticated user; **unprotected by SIA role** (`login_required` only) | `accounts/access_map.html` | 200 | 200 (flagged) | 302 to login |
| `overview` | `/accounts/` | `accounts.views.overview` | GET | Any authenticated user; **unprotected by SIA role** (`login_required` only) | `accounts/overview.html` | 200 | 200 (flagged) | 302 to login |
| `password_change` | `/accounts/password/change/` | `accounts.views.ProjectPasswordChangeView` | GET, POST | Any authenticated user; **unprotected by SIA role** (`LoginRequiredMixin` only) | `accounts/password_change.html` | 200 | 200 (flagged) | 302 to login |
| `logout` | `/accounts/logout/` | Django `LogoutView` | POST only | Session logout; CSRF required; no SIA role check | Redirect to login | 302 with valid CSRF | 302 with valid CSRF | 302 with valid CSRF; 403 without CSRF |
| `access_denied` | `/accounts/denied/` | `accounts.views.access_denied` | GET | Any authenticated user; **unprotected by SIA role** (`login_required` only); intentionally renders a denial | `accounts/access_denied.html` (403) | 403 | 403 (flagged) | 302 to login |

4A role-guard finding: `dashboard`, `access_map`, `overview`, `password_change`, and `access_denied` have no SIA-role check and are marked unprotected above. The dashboard returns 200 even to an authenticated unknown-role user. The account pages also intentionally support no-role account states/self-service; no role policy was inferred or changed during this front-end freeze. Login/logout endpoints are public/session endpoints by design.

Module roles are from `operations/modules.py`; `act` roles may open the demo form, while both `read` and `act` roles may open lists and details:

| Module key | Roles with access |
|---|---|
| `needs` | `enduser-maintenance-lead` (act), `pr-creator` (read), `odm` (read), `procurement-specialist` (read) |
| `requests` | `enduser-maintenance-lead` (read), `pr-creator` (act), `odm` (act), `procurement-specialist` (read), `procurement-site-lead` (read), `procurement-strategic-lead` (read), `sic-stockroom-gr-creator` (read) |
| `quotations` | `procurement-specialist` (act), `procurement-site-lead` (read), `procurement-strategic-lead` (read) |
| `orders` | `procurement-specialist`, `procurement-site-lead`, `procurement-strategic-lead` (act); `sic-stockroom-gr-creator`, `dct`, `accounting-finance` (read) |
| `deliveries` | `enduser-maintenance-lead` (read), `sic-stockroom-gr-creator` (act), `dct` (read) |
| `issues` | `enduser-maintenance-lead`, `sic-stockroom-gr-creator` (act) |
| `invoices` | `dct`, `accounting-finance` (act) |

The Django admin exposes these additional named routes. Its role system is Django `is_active`/`is_staff` plus model permissions; no SIA role is mapped to staff status. Authorized-staff responses that need the database are not exercised because migrations are prohibited and the database is empty.

| URL name | Path | View | Methods | Roles allowed / guard | Template or response | Authorized staff | Non-staff SIA role | Anonymous |
|---|---|---|---|---|---|---|---|---|
| `admin:index` | `/admin/` | `AdminSite.index` | GET | Active staff; admin permissions | `admin/index.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:login` | `/admin/login/` | `AdminSite.login` | GET, POST | Public sign-in | `admin/login.html` | 302 if already authorized | 200 | 200 |
| `admin:logout` | `/admin/logout/` | `AdminSite.logout` | POST | Active staff wrapper; CSRF required | `registration/logged_out.html` | POST 200; GET 405 | 302 to admin login | 302 to admin login |
| `admin:password_change` | `/admin/password_change/` | `AdminSite.password_change` | GET, POST | Active staff | `admin/password_change_form.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:password_change_done` | `/admin/password_change/done/` | `AdminSite.password_change_done` | GET | Active staff | `admin/password_change_done.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:autocomplete` | `/admin/autocomplete/` | `AdminSite.autocomplete_view` | GET | Active staff plus model permissions | JSON response | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:jsi18n` | `/admin/jsi18n/` | `AdminSite.i18n_javascript` | GET | Active staff | JavaScript response | 200 expected; not exercised | 302 to admin login | 302 to admin login |
| `admin:view_on_site` | `/admin/r/<content_type_id>/<object_id>/` | `contenttypes.views.shortcut` via `AdminSite.admin_view` | GET | Active staff | Redirect response | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_group_changelist` | `/admin/auth/group/` | `GroupAdmin.changelist_view` | GET | Active staff plus group view permission | `admin/change_list.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_group_add` | `/admin/auth/group/add/` | `GroupAdmin.add_view` | GET, POST | Active staff plus group add permission | `admin/change_form.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_group_history` | `/admin/auth/group/<object_id>/history/` | `GroupAdmin.history_view` | GET | Active staff plus group view permission | `admin/object_history.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_group_delete` | `/admin/auth/group/<object_id>/delete/` | `GroupAdmin.delete_view` | GET, POST | Active staff plus group delete permission | `admin/delete_confirmation.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_group_change` | `/admin/auth/group/<object_id>/change/` | `GroupAdmin.change_view` | GET, POST | Active staff plus group change permission | `admin/change_form.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_user_password_change` | `/admin/auth/user/<id>/password/` | `UserAdmin.user_change_password` | GET, POST | Active staff plus user change permission | `admin/auth/user/change_password.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_user_changelist` | `/admin/auth/user/` | `UserAdmin.changelist_view` | GET | Active staff plus user view permission | `admin/change_list.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_user_add` | `/admin/auth/user/add/` | `UserAdmin.add_view` | GET, POST | Active staff plus user add permission | Django user-admin add form | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_user_history` | `/admin/auth/user/<object_id>/history/` | `UserAdmin.history_view` | GET | Active staff plus user view permission | `admin/object_history.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_user_delete` | `/admin/auth/user/<object_id>/delete/` | `UserAdmin.delete_view` | GET, POST | Active staff plus user delete permission | `admin/delete_confirmation.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:auth_user_change` | `/admin/auth/user/<object_id>/change/` | `UserAdmin.change_view` | GET, POST | Active staff plus user change permission | `admin/auth/user/change_form.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |
| `admin:app_list` | `/admin/auth/` | `AdminSite.app_index` | GET | Active staff plus app permissions | `admin/app_index.html` | DB-dependent; not verified | 302 to admin login | 302 to admin login |

## Context variables by screen

Every screen extends `base.html` and therefore reads the shared shell context: `brand_name`, `brand_sub`, `nav_modules` (`url`, `key`, `label`), `active_module`, `request.resolver_match.url_name`, `user.get_username`, `role.label`, `crumb_parent`, `crumb_current`, and `messages`. The sidebar includes `partials/mark.svg`; the topbar reads the breadcrumb and role values. Defaults in the templates are presentation fallbacks, not backend data.

| Screen | Additional context values read |
|---|---|
| Dashboard | `role.label`, `role_description`, `primary_action.url`/`label`, `records_connected`, `module_count`; `metrics[]` (`label`, `value`, `unit`, `source`); `modules[]` (`url_name`, `key`, `url`, `label`, `description`); `queue[]` (`title`, `subtitle`, optional `time`); `status.source`/`last_sync` |
| Records list | `module.key`/`label`/`access`; `record_count`, `data_source`, `columns[]` (`label`, `kind`), `rows[][]` cells (`kind`, `value`, optional `tone`); empty-state `title`, `body`, optional `action_label`/`action_url` |
| Record detail | `reference`, `module.key`/`label`/`url`/`access`, `status`; `fields[]` (`label`, `value`); `chain[]` (`module_key`, `reference`); `actions[]` (`url`, `label`); `action_message` |
| Demonstration form | `module.label`, `form` (bound Django form and its fields/errors/help text), `cancel_url` |
| Access map | `roles[]` (`label`, `purpose`, `allowed_modules[]` with `label`/`access`, `unavailable_modules[]` with `label`, `capabilities[]`) |
| Workspaces | `roles[]` (`label`) |
| Login | `form` (Django `AuthenticationForm`, field labels/IDs/errors/help text) |
| Password change | `form` (Django `PasswordChangeForm`, field labels/IDs/errors/help text) |
| Access denied | `denial_reason`, `attempted_route` |

`partials/field.html` reads `field.label`, `field.id_for_label`, `field.errors`, and optional `field.help_text`. `partials/messages.html` reads `messages`. `partials/empty_state.html` reads `title`, `body`, and optional `action_label`/`action_url`.

## Partials and consumers

| Partial | Included by |
|---|---|
| `partials/sidebar.html` (and its `partials/mark.svg`) | Every screen through `base.html` |
| `partials/topbar.html` | Every screen through `base.html` |
| `partials/messages.html` | Every screen through `base.html` |
| `partials/field.html` | Login, password change, demonstration form |
| `operations/partials/empty_state.html` | Records list, record detail, dashboard when no modules, access map when no role, workspaces when no role |
| `operations/partials/metric_strip.html` | Dashboard |
| `operations/partials/module_tiles.html` | Dashboard |
| `operations/partials/queue_list.html` | Dashboard |
| `operations/partials/system_status.html` | Dashboard |
| `operations/partials/records_table.html` | Records list |

## Backend plug-in contract

- `records_connected`: boolean; `true` only when the dashboard's displayed records are backed by actual database rows.
- `metrics`: four dictionaries with `label`, `value` (scalar or `None`), `unit`, and `source`; labels are Open needs, Awaiting my action, Delivered, Stock alerts.
- `modules`: ordered dictionaries with `key`, `label`, `description`, `url_name`, `url`, and `access` (`act` or `read`); `module_tiles` resolves `url_name` with `key`.
- `queue`: iterable of dictionaries with `title`, `subtitle`, and optional `time`; an empty iterable triggers the waiting empty state.
- `status`: dictionary with `source` and `last_sync`, both display-ready strings.
- `fields`: ordered iterable of dictionaries with `label` and display-ready `value`.
- `chain`: ordered iterable of linked-record dictionaries with `module_key` and `reference`.
- `actions`: iterable of permitted action dictionaries with `url` and `label`; omit unauthorized actions rather than sending disabled actions.
- `rows`: iterable of rows, each an iterable of cells with `kind`, `value`, and optional `tone`; `kind` is `number`, `reference`, `status`, or plain text. An empty iterable renders the empty state, not a fake row.
- `columns`: ordered iterable of dictionaries with `label` and optional `kind`; `kind == "number"` right-aligns the header and cells.
- `access`: module permission string (`act` or `read`); access-map roles also provide `allowed_modules`, `unavailable_modules`, and `capabilities`, with each allowed module carrying its `label` and `access`.

## Screen inventory

Existing screens: dashboard; generic records list for registered modules; generic record detail; demonstration-only form; access map; workspaces; login; password change; access denied. Empty, read-only, and denied states use these same templates.

Not implemented: `accounts/health.html`/health route; model-backed record creation or editing; populated lists/details/record chains; sourced dashboard metrics and queue; connected SAP, email, or payment processing; custom 404/500 screens. The demonstration form does not save.

## CSS class inventory

All classes defined in `static/css/main.css` (including state/modifier classes):

`shell`, `side`, `main`, `content`, `cols`, `auth-wrap`, `skip`, `brand`, `mark-frame`, `mark-glyph`, `brand-name`, `brand-sub`, `nav`, `nav-label`, `nav-item`, `on`, `side-foot`, `avatar`, `who`, `topbar`, `crumb`, `topbar-right`, `role-pill`, `page-head`, `actions`, `btn`, `btn-primary`, `btn-ghost`, `strip`, `metric`, `num`, `unit`, `src`, `panel`, `panel-head`, `count`, `right`, `filter`, `panel-body`, `r`, `mono`, `status`, `pager`, `mini`, `t`, `tiles`, `tile`, `k`, `go`, `kv`, `form`, `field`, `req`, `input`, `checkbox`, `hint`, `err`, `alert`, `bad`, `ok`, `empty`, `note`, `soonbox`, `badge`, `auth-card`, `sub`, `auth-foot`, `btn-block`, `theme-btn`, `soon`, `tone-ok`, `tone-warn`, `tone-danger`, `tone-info`, `dot`, `warn`, `danger`, `info`, `frame`, `row`, `stack`, `mt`, `muted`, `small`, `table-scroll`.
