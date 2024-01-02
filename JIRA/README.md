## Trend Vision One™ JIRA connector

#### Prerequisites
- [Python 3.7](https://www.python.org/downloads/) or newer.
- Trend Vision One account with a chosen region - [Trend Vision One documentation](https://github.com/trendmicro/tm-v1-fs-python-sdk#:~:text=Trend%20Vision%20One%20documentation).
- Trend Vision One API key with proper role - [Trend Vision One API key documentation](https://github.com/trendmicro/tm-v1-fs-python-sdk#:~:text=Trend%20Vision%20One%20API%20key%20documentation).

#### Features
- Create issue from Trend Vision One workbench alerts
- Add note with jira number to the workbench alert
- Update issue based on workbench alert status/jira status
- Customisable JIRA field mapping
    
#### YAML Configuration
The configuration of this project is based on YAML config file [config.yml](config.yml).
Please check this file for a reference implementation and adapt it to your project requirements.

##### General
| config path | parameter          | description                                                                                                |
|:------------|:-------------------|:-----------------------------------------------------------------------------------------------------------|
| app         | poll_time          | Poll time in seconds.                                                                                      |
| app.alert   | start_time         | Workbench alerts retrieval start time (UTC timezone), If empty, defaults to the time the request is made.  |
| app.alert   | end_time           | Workbench alerts retrieval end time (UTC timezone), If empty, defaults to the time the request is made.    |
| app.alert   | skip_closed        | Skip closed alerts in Vision One, else create a new JIRA and re-open the alert.                            |
| app.log     | debug              | Enable debug logging.                                                                                      |
| app.log     | to_file            | Enable logging to file instead of stdout.                                                                  |
| app.log     | filename           | Log filename                                                                                               |
| app.log     | file_size          | Log file max size in MB                                                                                    |
| app.log     | file_count         | Number of log files to keep                                                                                |

##### Vision One
| config path | parameter          | description                                                                                                |
|:------------|:-------------------|:-----------------------------------------------------------------------------------------------------------|
| v1          | url                | Vision One API URL                                                                                         |
| v1          | token              | Vision One API Token                                                                                       |

##### JIRA
| config path | parameter          | description                                                                                                |
|:------------|:-------------------|:-----------------------------------------------------------------------------------------------------------|
| jira        | url                | JIRA URL                                                                                                   |
| jira        | username           | JIRA Cloud Username (User email address associated to the API Token), If using JIRA On-premise leave empty |
| jira        | token              | JIRA Cloud API Token or On-premise Personal Authentication Token                                           |

##### Summary prefix mapping
| config path | parameter          | description                                                                                                |
|:------------|:-------------------|:-----------------------------------------------------------------------------------------------------------|
| mapping     | summary_prefix     | Prefix to use for the issue summary, If not required leave empty                                           |

##### JIRA key-value mapping
| config path      | parameter          | description                                                                  |
|:-----------------|:-------------------|:-----------------------------------------------------------------------------|
| mapping.static[] | key                | JIRA field key (i.e: project, label, customfield_12345, ...)                 |
|                  | value              | JIRA field value (i.e: 123456, "label1,label2,label3", "string", value_name) |
|                  | type               | JIRA field value type (id, array, string, name)                              |

##### Workbench Alert key-value mapping
Map JIRA field to Vision One Workbench Alerts attributes returned by API [Get alert details](https://automation.trendmicro.com/xdr/api-v3#tag/Workbench/paths/~1v3.0~1workbench~1alerts/get).
Optional mapping available to map multiple JIRA values with Vision One attributes values. (i.e: priority 'P3' in JIRA mapped to Vision One severity 'low').

| config path       | parameter | description                                            |
|:------------------|:----------|:-------------------------------------------------------|
| mapping.dynamic[] | key       | JIRA field (i.e: priority)                             |
|                   | value     | Vision One Alert field (i.e: severity)                 |
|                   | type      | JIRA field value type (id, array, string, name, value) |
|                   | mapping   | (optional) JIRA field value mapping (i.e: P3: low)     |

###### Status
Map JIRA status to Vision One Alert status.

| config path               | parameter | description                      |
|:--------------------------|:----------|:---------------------------------|
| mapping.status[]          | key       | JIRA status                      |
|                           | value     | Vision One Alert status          |
| mapping.status[].fields[] | key       | JIRA field key (i.e: resolution) |
|                           | value     | JIRA field value (i.e: 123456)   |
|                           | type      | JIRA field type (i.e: id)        | 

#### Quick start
Installation
```
pip install pytmv1
```