# PostNord package tracking for Home Assistant

Home Assistant integration that follows the parcels of a PostNord account.

[![GitHub Release][releases-shield]][releases] [![GitHub Release Date][release-date-shield]][releases] [![HACS][hacs-shield]][hacs] [![License][license-shield]](LICENSE)

<img src="https://raw.githubusercontent.com/jesmak/postnord_tracking/main/docs/images/dashboard-light.png#gh-light-mode-only" width="560" alt="A dashboard with the counts of incoming packages on the way and ready for pickup, and package-tracker-card listing a parcel ready for pickup at a service point, one sent to someone else, one on its way and one delivered, each marked incoming or sent">
<img src="https://raw.githubusercontent.com/jesmak/postnord_tracking/main/docs/images/dashboard-dark.png#gh-dark-mode-only" width="560" alt="A dashboard with the counts of incoming packages on the way and ready for pickup, and package-tracker-card listing a parcel ready for pickup at a service point, one sent to someone else, one on its way and one delivered, each marked incoming or sent">

## What is it?

A custom component that lists the coming and recently delivered parcels of a [PostNord](https://www.postnord.fi/)
account, and those sent from it, telling the two apart. There's no need to add parcels by hand. The list comes from the
parcels in your account, and it's updated every 10 minutes. PostNord keeps delivered parcels in the account too, so
recent deliveries stay listed for as long as you choose.

It has been made and tested with a Finnish PostNord account. The login and the service are the same PostNord app ones in
Sweden, Denmark and Norway, so accounts there should work as well, but they haven't been tried.

The sensor lists the packages in the format [package-tracker-card](https://github.com/jesmak/package-tracker-card)
reads, so the card can show them together with packages from other tracking integrations. Four more sensors count the
packages coming to you and those you have sent, and an event entity fires when one of them moves along.

This is an unofficial integration. See [Data](#data) for what that means.

## Installation

### With HACS

1. Add this repository to HACS custom repositories with type **Integration**
2. Search for PostNord package tracking in HACS and download it
3. Restart Home Assistant
4. Add the integration in Settings › Devices & services and log in (see [Logging in](#logging-in))

### Manual

1. Download the source code from the latest release
2. Copy the `custom_components/postnord_tracking` folder to your Home Assistant installation's
   `config/custom_components` folder
3. Restart Home Assistant
4. Add the integration in Settings › Devices & services and log in (see [Logging in](#logging-in))

### Logging in

PostNord has no public API for a person's own parcels. The integration uses the same service the PostNord app does,
with the app's login. That login finishes in the PostNord app (at the address `com.postnord.app://redirect`), not back
in Home Assistant, so its last address is copied over by hand. The setup form shows these steps with the login link.

1. Open an empty browser tab and press **F12**. On the **Network** tab, turn on **Preserve log**, in Firefox **Persist
   Logs** under the gear. Without it, the list is cleared when the login finishes.
2. Right-click the login link on the form, copy it, open it in that tab and log in. If you're already logged in to
   PostNord, it finishes at once. That's expected.
3. Type `code=` in the Network filter and copy the address that starts with `com.postnord.app://redirect?code=`. If it
   isn't listed, it's in the **Location** response header of the last `account.postnord.com` request.
4. Paste it into the form and continue **within a few minutes**. The code expires quickly and works only once. If it's
   refused, log in again with the same link.

The account is named after its email address, which PostNord supplies, and the settings come next. After that the
integration renews its own access. If PostNord stops accepting it, Home Assistant asks you to log in again the same
way. Deleting the account in Home Assistant ends its login at PostNord as well.

Because it imitates the app, a change in PostNord's service can stop the integration until it is updated.

## Settings

Each account is added separately. To change its settings, or to log in again, choose **Reconfigure** from the
account's menu on the integration page.

| Name                                       | Type    | Description                                                                      | Default                   |
| ------------------------------------------ | ------- | -------------------------------------------------------------------------------- | ------------------------- |
| Language                                   | enum    | Language of the package event descriptions, `fi`, `sv`, `nb`, `da` or `en`       | Home Assistant's language |
| Undelivered packages first                 | boolean | When there are more packages than the maximum, undelivered ones are listed first | on                        |
| Maximum number of incoming packages        | number  | How many incoming packages the sensor lists. 0 leaves them out altogether        | 5                         |
| Maximum number of sent packages            | number  | How many sent packages the sensor lists. 0 leaves them out altogether            | 5                         |
| Days until undelivered packages are hidden | days    | Counted from the latest event. Some packages stay in delivery for good           | 15                        |
| Days until delivered packages are hidden   | days    | Counted from the delivery. Returned packages count as delivered                  | 3                         |
| Pickup code                                | enum    | Don't add, or add                                                                | don't add                 |

PostNord gives the pickup code only to a login made with strong identification, which the integration can't make yet.
So the code stays empty whatever **Pickup code** says. The setting is there for when it can, and keeps the code out
until then. The pickup point is always included.

## Sensors

### Packages

The state is the time a parcel of the account last changed, such as when it was registered, moved or delivered. The
sensor is named after the account, for example `sensor.postnord_matti_meikalainen_example_com`.

The `packages` attribute lists the parcels, and each package has these keys.

| Key                                         | Description                                                                         |
| ------------------------------------------- | ----------------------------------------------------------------------------------- |
| `shipment_number`                           | PostNord's shipment id, which is the tracking number                                |
| `status`                                    | The package's status, below                                                         |
| `raw_status`                                | PostNord's status, such as `AVAILABLE_FOR_DELIVERY`                                 |
| `direction`                                 | `incoming`, or `outgoing` when sent from the account. Empty if not known            |
| `origin`, `origin_city`                     | The sender and its city. Empty for a package you sent                               |
| `recipient`                                 | Who a package you sent goes to, when PostNord says                                  |
| `destination`, `destination_city`           | The pickup point when PostNord names one, and the receiver's city                   |
| `shipment_date`                             | When the parcel turned up in the account                                            |
| `latest_event`                              | The latest event, in the chosen language                                            |
| `latest_event_city`, `latest_event_country` | Where the latest event happened, with the receiver's country if PostNord gives none |
| `latest_event_date`                         | When the package last changed                                                       |
| `estimated_delivery`                        | When the package is expected, when PostNord says                                    |
| `pickup_deadline`                           | How long it is kept at the pickup point. PostNord doesn't tell, so it is empty      |
| `weight`                                    | The package's weight in kilograms                                                   |
| `package_count`                             | How many parcels the shipment has                                                   |
| `pickup_point`                              | The pickup point, with `name`, `street`, `postal_code`, `city`, `type`, `available` |
| `pickup_code`                               | The code that collects the package. Always empty for now, see [Settings](#settings) |
| `pickup_qr`                                 | Always empty, until it is known which PostNord points scan a QR code                |
| `source`                                    | Always `PostNord`                                                                   |
| `tracking_url`                              | The package's page on PostNord's tracking site                                      |

| `status` | Meaning                | PostNord's status                |
| -------- | ---------------------- | -------------------------------- |
| `1`      | Waiting                | `CREATED`, `INFORMED`            |
| `3`      | In transport           | `EN_ROUTE`, `DELAYED`            |
| `5`      | Ready for pickup       | `AVAILABLE_FOR_DELIVERY`         |
| `0`      | Delivered              | `DELIVERED`                      |
| `6`      | Returned to the sender | `RETURNED`, `DELIVERY_REFUSED`   |
| `7`      | Unknown                | `DELIVERY_IMPOSSIBLE`, any other |

PostNord has no separate "received" or "in delivery" status, so `2` and `4` aren't used.

A parcel delivered home has no pickup point. Times are ISO 8601 with their zone. The packages aren't stored in the recorder,
only the state. The sensor is unavailable while PostNord can't be reached.

### Counts

Four sensors count the packages, so a badge or an automation needs no templating. They count every package of the
account within the days set above, also those the list has no room for. A package whose direction PostNord doesn't
give counts as incoming.

| Sensor                    | What it counts                                                     |
| ------------------------- | ------------------------------------------------------------------ |
| Incoming on the way       | Incoming packages that haven't finished their journey              |
| Incoming ready for pickup | Incoming packages waiting at a pickup point                        |
| Sent on the way           | Packages sent from the account that haven't finished their journey |
| Sent ready for pickup     | Sent packages waiting for the recipient at a pickup point          |

## Events

An event entity, **Package**, fires once for everything that happens to a package, so an automation can act on it
without watching the packages attribute. Several packages changing in one update fire one event each, packages the
list has no room for included. A new package that is already ready for pickup, delivered or returned when it is first
seen fires `new_package` and then that status's event, so an automation listening for either hears of it. Packages
sent from the account fire events too, with `direction` set to `outgoing`, so an automation about your own parcels
leaves them out with a condition, as in the example below.

| Event type         | When it fires                                 |
| ------------------ | --------------------------------------------- |
| `new_package`      | A package the account hadn't seen before      |
| `moved`            | The package moved along, or a new event of it |
| `ready_for_pickup` | It is waiting to be picked up                 |
| `delivered`        | It has been delivered                         |
| `returned`         | It was returned to the sender                 |

The event carries the package it happened to, with `shipment_number`, `status`, `raw_status`, `direction`, `origin`,
`destination`, `destination_city`, `latest_event`, `latest_event_city`, `latest_event_date` and `source`.

Nothing fires for the packages that are already there when Home Assistant starts, or when the integration is reloaded,
since they have not just happened. A change while Home Assistant was off fires nothing either. A package missing from
one of PostNord's answers and back in the next is compared with how it was, not reported as new.

## Examples

A notification for every package that can be picked up, leaving out the ones sent from the account. The trigger
watches every event, not only a change of its type, so the second package ready in a row isn't missed. `queued` keeps
the events of one update from being dropped.

```yaml
automation:
  - mode: queued
    triggers:
      - trigger: state
        entity_id: event.postnord_matti_meikalainen_example_com_package
        not_from: unavailable
        not_to:
          - unavailable
          - unknown
    conditions:
      - condition: state
        entity_id: event.postnord_matti_meikalainen_example_com_package
        attribute: event_type
        state: ready_for_pickup
      - condition: not
        conditions:
          - condition: state
            entity_id: event.postnord_matti_meikalainen_example_com_package
            attribute: direction
            state: outgoing
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "{{ trigger.to_state.attributes.shipment_number }} is ready for pickup"
```

The packages on a dashboard:

```yaml
type: custom:package-tracker-card
title: Packages
entity: sensor.postnord_matti_meikalainen_example_com
```

## Upgrading from 1.1

The one **Maximum number of packages** became two, one for incoming packages and one for sent ones. Both take the
number the account had. **Packages on the way** and **Packages ready for pickup** are now **Incoming on the way** and
**Incoming ready for pickup**, and no longer count packages sent from the account, which have sensors of their own.
Their entity IDs stay as they were. Events of sent packages still fire, now with `direction`. Add the condition in the
example above to an automation that should leave them out.

The account, the sensors, the event entity, their entity IDs and the other settings all carry over.

## Upgrading from 1.0

The pickup point is always included now, and the **Pickup point and code** switch became the **Pickup code** choice.
An account that had the switch on gets **Add**, and one that had it off gets **Don't add**.

The account, the sensors, the event entity, their entity IDs and the other settings all carry over.

## Data

Package data comes from PostNord Group AB, from the same service the PostNord app uses.

This is an unofficial integration. It isn't affiliated with or endorsed by PostNord. Each user logs in with their own
PostNord account, and using it may be against PostNord's terms of service, so use it at your own risk. It will be
withdrawn if PostNord objects.

## Translating

The integration's texts are in `custom_components/postnord_tracking/translations/`, one JSON file per language, named
by its language code, such as `en.json` and `fi.json`. To add a language, copy `en.json` to the new language's code
and translate the values.

## Development

Requires Python 3.14, the version the current Home Assistant needs.

```
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest
```

| Path                           | What it contains                                                           |
| ------------------------------ | -------------------------------------------------------------------------- |
| `__init__.py`                  | Setup, removal, and moving entries of earlier versions                     |
| `config_flow.py`               | Logging in, logging in again and changing settings                         |
| `api.py`                       | The app's login, the parcels query, renewing and revoking tokens           |
| `coordinator.py`               | Fetching the packages every 10 minutes                                     |
| `shipments.py`                 | Turning parcels into the sensor's packages                                 |
| `sensor.py`                    | The sensors, the account's own and the counts                              |
| `event.py`                     | The event entity, one event per package change                             |
| `changes.py`                   | What happened to the packages between two updates                          |
| `translations/<language>.json` | Home Assistant UI texts                                                    |
| `docs/screenshots.json`        | The made-up data the README's image is taken from                          |
| `tools/pnpaste.py`             | The same login on the command line, saving the tokens to a file only you can read |

## Support

Hey dude! Help me out for a couple of :beers: or a :coffee:!

[![coffee](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/jesmak)

## License

MIT, see [LICENSE](LICENSE).

[releases-shield]: https://img.shields.io/github/release/jesmak/postnord_tracking.svg?style=for-the-badge
[release-date-shield]: https://img.shields.io/github/release-date/jesmak/postnord_tracking?style=for-the-badge
[releases]: https://github.com/jesmak/postnord_tracking/releases
[hacs-shield]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[hacs]: https://hacs.xyz/docs/faq/custom_repositories/
[license-shield]: https://img.shields.io/github/license/jesmak/postnord_tracking.svg?style=for-the-badge
