# PostNord package tracking for Home Assistant

Home Assistant integration that follows the parcels of a PostNord account.

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![GitHub Activity][commits-shield]][commits]

## Support

Hey dude! Help me out for a couple of :beers: or a :coffee:!

[![coffee](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/jesmak)

## What is it?

A custom component that lists the coming and recently delivered parcels of a [PostNord](https://www.postnord.fi/)
account. There's no need to add parcels by hand: the list comes from the parcels in your account, and it's updated
every 10 minutes. PostNord keeps delivered parcels in the account too, so recent deliveries stay listed for as long as
you choose.

It has been made and tested with a Finnish PostNord account. The login and the service are the same PostNord app
ones in Sweden, Denmark and Norway, so accounts there should work as well, but they haven't been tried.

The sensor lists the packages in the format [package-tracker-card](https://github.com/jesmak/package-tracker-card)
reads, so the card can show them together with packages from other tracking integrations.

## Installation

### With HACS

1. Add this repository to HACS custom repositories with type **Integration**
2. Search for PostNord package tracking in HACS and download it
3. Restart Home Assistant
4. Add the integration in Settings › Devices & services and log in as described below

### Manual

1. Download the source code from the latest release
2. Copy the `custom_components/postnord_tracking` folder to your Home Assistant installation's
   `config/custom_components` folder
3. Restart Home Assistant
4. Add the integration in Settings › Devices & services and log in as described below

## Logging in

PostNord has no public API for a person's own parcels. The integration uses the same service the PostNord app does,
with the app's login. That login finishes in the PostNord app (at the address `com.postnord.app://redirect`), not back
in Home Assistant, so its last address is copied over by hand. The setup form shows these steps with the login link:

1. Open an empty browser tab and press **F12**. On the **Network** tab, turn on **Preserve log** (Firefox: **Persist
   Logs** under the gear). Without it, the list is cleared when the login finishes.
2. Right-click the login link on the form, copy it, open it in that tab and log in. If you're already logged in to
   PostNord, it finishes at once. That's expected.
3. Type `code=` in the Network filter and copy the address that starts with `com.postnord.app://redirect?code=`. If it
   isn't listed, it's in the **Location** response header of the last `account.postnord.com` request.
4. Paste it into the form and continue **within a few minutes**. The code expires quickly and works only once; if it's
   refused, log in again with the same link.

The account is named after its email address, which PostNord supplies, and the settings come next. After that the
integration renews its own access. If PostNord stops accepting it, Home Assistant asks you to log in again the same
way.

Because it imitates the app, a change in PostNord's service can stop the integration until it is updated.

## Settings

Each account is added separately. To change its settings, or to log in again, choose **Reconfigure** from the
account's menu on the integration page.

| Name                                       | Type    | Description                                                                             | Default                   |
| ------------------------------------------ | ------- | --------------------------------------------------------------------------------------- | ------------------------- |
| Language                                   | enum    | Language of the package event descriptions: `fi`, `sv`, `nb`, `da` or `en`              | Home Assistant's language |
| Undelivered packages first                 | boolean | When there are more packages than the maximum, undelivered ones are listed first        | on                        |
| Maximum number of packages                 | number  | How many packages the sensor lists                                                      | 5                         |
| Days until undelivered packages are hidden | days    | Counted from the latest event. Some packages stay in delivery for good                  | 15                        |
| Days until delivered packages are hidden   | days    | Counted from the delivery. Returned packages count as delivered                         | 3                         |
| Pickup point and code                      | boolean | Adds the pickup point to the packages, and the pickup code once PostNord's is supported | off                       |

## Sensor

The state is the time a parcel of the account last changed, such as when it was registered, moved or delivered. The
sensor is named after the account, for example `sensor.postnord_matti_meikalainen_example_com`.

The `packages` attribute lists the parcels, and each package has:

| Key                                         | Description                                                                        |
| ------------------------------------------- | ---------------------------------------------------------------------------------- |
| `shipment_number`                           | PostNord's shipment id, which is the tracking number                               |
| `status`                                    | The package's status, below                                                        |
| `raw_status`                                | PostNord's status, such as `AVAILABLE_FOR_DELIVERY`                                |
| `origin`, `origin_city`                     | The sender and its city                                                            |
| `destination`, `destination_city`           | The pickup point when PostNord names one, and the receiver's city                  |
| `shipment_date`                             | When the parcel turned up in the account                                           |
| `latest_event`                              | The latest event, in the chosen language                                           |
| `latest_event_city`, `latest_event_country` | Where the latest event happened, and the receiver's country                        |
| `latest_event_date`                         | When the package last changed                                                      |
| `estimated_delivery`                        | When the package is expected, when PostNord says                                   |
| `pickup_deadline`                           | How long it is kept at the pickup point, which PostNord doesn't tell: always empty |
| `weight`                                    | The package's weight in kilograms                                                  |
| `package_count`                             | How many parcels the shipment has                                                  |
| `pickup_point`                              | The pickup point, with **Pickup point and code** on                                |
| `pickup_code`                               | The code that collects the package. Always empty for now, see below                |
| `source`                                    | Always `PostNord`                                                                  |
| `tracking_url`                              | The package's page on PostNord's tracking site                                     |

| `status` | Meaning                | PostNord's status                |
| -------- | ---------------------- | -------------------------------- |
| `1`      | Waiting                | `CREATED`, `INFORMED`            |
| `3`      | In transport           | `EN_ROUTE`, `DELAYED`            |
| `5`      | Ready for pickup       | `AVAILABLE_FOR_DELIVERY`         |
| `0`      | Delivered              | `DELIVERED`                      |
| `6`      | Returned to the sender | `RETURNED`, `DELIVERY_REFUSED`   |
| `7`      | Unknown                | `DELIVERY_IMPOSSIBLE`, any other |

PostNord has no separate "received" or "in delivery" status, so `2` and `4` aren't used.

PostNord gives the pickup code only to a login made with strong identification, which the integration can't make yet,
so `pickup_code` stays empty. The pickup point is left out unless the account's **Pickup point and code** setting is
turned on. Change the setting with **Reconfigure**.

Times are ISO 8601 in UTC. The packages aren't stored in the recorder, only the state. The sensor is unavailable while
PostNord can't be reached.

## Counts

Two sensors count the packages, so a badge or an automation needs no templating:

| Sensor                    | What it counts                              |
| ------------------------- | ------------------------------------------- |
| Packages on the way       | Everything that hasn't finished its journey |
| Packages ready for pickup | The ones waiting at a pickup point          |

## Events

An event entity, **Package**, fires once for everything that happens to a package, so an automation can act on it
without watching the packages attribute. Several packages changing in one update fire one event each.

| Event type         | When it fires                                 |
| ------------------ | --------------------------------------------- |
| `new_package`      | A package the account hadn't seen before      |
| `moved`            | The package moved along, or a new event of it |
| `ready_for_pickup` | It is waiting to be picked up                 |
| `delivered`        | It has been delivered                         |
| `returned`         | It was returned to the sender                 |

The event carries the package it happened to: `shipment_number`, `status`, `raw_status`, `origin`, `destination`,
`destination_city`, `latest_event`, `latest_event_city`, `latest_event_date` and `source`.

Nothing fires for the packages that are already there when Home Assistant starts; they have not just happened.

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: event.postnord_matti_meikalainen_example_com_package
        attribute: event_type
        to: ready_for_pickup
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "{{ trigger.to_state.attributes.shipment_number }} is ready for pickup"
```

## Data

Package data: PostNord Group AB, from the same service the PostNord app uses.

## Development

Requires Python 3.14.

```
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check .
```

| Path                           | What it contains                                       |
| ------------------------------ | ------------------------------------------------------ |
| `__init__.py`                  | Setup                                                  |
| `config_flow.py`               | Logging in, logging in again and changing settings     |
| `api.py`                       | The app's login, the parcels query and renewing tokens |
| `coordinator.py`               | Fetching the packages every 10 minutes                 |
| `shipments.py`                 | Turning parcels into the sensor's packages             |
| `sensor.py`                    | The sensors: the account's own, and the counts         |
| `event.py`                     | The event entity, one event per package change         |
| `changes.py`                   | What happened to the packages between two updates      |
| `translations/<language>.json` | Home Assistant UI texts                                |

`tools/pnpaste.py` makes the same login on the command line and prints the tokens, for calling the API by hand.

[commits-shield]: https://img.shields.io/github/commit-activity/y/jesmak/postnord_tracking.svg?style=for-the-badge
[commits]: https://github.com/jesmak/postnord_tracking/commits/master
[license-shield]: https://img.shields.io/github/license/jesmak/postnord_tracking.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/jesmak/postnord_tracking.svg?style=for-the-badge
[releases]: https://github.com/jesmak/postnord_tracking/releases
