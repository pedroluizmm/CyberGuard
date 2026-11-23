// Gerado por docs/apresentacao/dados_slides.py a partir das evidências; não editar à mão.
window.ESCALA = {
 "generated_from": [
  "benchmarks/results/summary.json",
  "data/bulk/reports"
 ],
 "sizes": [
  1000000,
  2000000
 ],
 "ops": [
  {
   "id": "e1_read_by_id",
   "exp": "E1",
   "label": "READ por UUID",
   "class": "chave",
   "points": [
    {
     "n": 1000000,
     "pg": 1.639,
     "cs": 1.76,
     "pg_db": 0.528,
     "cs_db": 0.733,
     "faster": "postgresql",
     "ratio": 1.07,
     "covered": null,
     "equivalent": true,
     "replicates": []
    },
    {
     "n": 2000000,
     "pg": 1.674,
     "cs": 2.383,
     "pg_db": 0.526,
     "cs_db": 1.083,
     "faster": "postgresql",
     "ratio": 1.42,
     "covered": null,
     "equivalent": true,
     "replicates": [
      {
       "run_id": "20261123T202101Z-main",
       "postgresql": 2.351,
       "cassandra": 2.886,
       "faster": "postgresql",
       "ratio": 1.23
      }
     ]
    }
   ]
  },
  {
   "id": "q1_device_hot_page",
   "exp": "E2",
   "label": "Q1 dispositivo, página 100",
   "class": "pagina_fixa",
   "points": [
    {
     "n": 1000000,
     "pg": 3.881,
     "cs": 8.527,
     "pg_db": 1.812,
     "cs_db": 5.957,
     "faster": "postgresql",
     "ratio": 2.2,
     "covered": 13478,
     "equivalent": true,
     "replicates": []
    },
    {
     "n": 2000000,
     "pg": 4.152,
     "cs": 8.206,
     "pg_db": 1.92,
     "cs_db": 5.581,
     "faster": "postgresql",
     "ratio": 1.98,
     "covered": 27136,
     "equivalent": true,
     "replicates": [
      {
       "run_id": "20261123T202101Z-main",
       "postgresql": 5.426,
       "cassandra": 10.8,
       "faster": "postgresql",
       "ratio": 1.99
      }
     ]
    }
   ]
  },
  {
   "id": "q1_device_hot_10pages",
   "exp": "E2",
   "label": "Q1 10 páginas (1.000)",
   "class": "pagina_fixa",
   "points": [
    {
     "n": 1000000,
     "pg": 32.287,
     "cs": 94.975,
     "pg_db": 15.467,
     "cs_db": 64.931,
     "faster": "postgresql",
     "ratio": 2.94,
     "covered": 13478,
     "equivalent": true,
     "replicates": []
    },
    {
     "n": 2000000,
     "pg": 31.748,
     "cs": 90.41,
     "pg_db": 14.861,
     "cs_db": 58.62,
     "faster": "postgresql",
     "ratio": 2.85,
     "covered": 27136,
     "equivalent": true,
     "replicates": [
      {
       "run_id": "20261123T202101Z-main",
       "postgresql": 37.341,
       "cassandra": 99.531,
       "faster": "postgresql",
       "ratio": 2.67
      }
     ]
    }
   ]
  },
  {
   "id": "q1_device_cold_page",
   "exp": "E2",
   "label": "Q1 dispositivo pouco ativo",
   "class": "resposta_crescente",
   "points": [
    {
     "n": 1000000,
     "pg": 3.079,
     "cs": 11.26,
     "pg_db": 1.28,
     "cs_db": 9.103,
     "faster": "postgresql",
     "ratio": 3.66,
     "covered": 54,
     "equivalent": true,
     "replicates": []
    },
    {
     "n": 2000000,
     "pg": 3.704,
     "cs": 12.972,
     "pg_db": 1.784,
     "cs_db": 10.181,
     "faster": "postgresql",
     "ratio": 3.5,
     "covered": 113,
     "equivalent": true,
     "replicates": [
      {
       "run_id": "20261123T202101Z-main",
       "postgresql": 4.486,
       "cassandra": 13.579,
       "faster": "postgresql",
       "ratio": 3.03
      }
     ]
    }
   ]
  },
  {
   "id": "q2_ip_hot_page",
   "exp": "E3",
   "label": "Q2 IP de campanha",
   "class": "pagina_fixa",
   "points": [
    {
     "n": 1000000,
     "pg": 4.848,
     "cs": 11.64,
     "pg_db": 2.118,
     "cs_db": 8.802,
     "faster": "postgresql",
     "ratio": 2.4,
     "covered": 11522,
     "equivalent": true,
     "replicates": []
    },
    {
     "n": 2000000,
     "pg": 3.97,
     "cs": 10.584,
     "pg_db": 1.841,
     "cs_db": 7.7,
     "faster": "postgresql",
     "ratio": 2.67,
     "covered": 23124,
     "equivalent": true,
     "replicates": [
      {
       "run_id": "20261123T202101Z-main",
       "postgresql": 3.855,
       "cassandra": 9.919,
       "faster": "postgresql",
       "ratio": 2.57
      }
     ]
    }
   ]
  },
  {
   "id": "q3_alerts_page",
   "exp": "E3",
   "label": "Q3 alertas severidade 3",
   "class": "pagina_fixa",
   "points": [
    {
     "n": 1000000,
     "pg": 3.934,
     "cs": 7.974,
     "pg_db": 1.769,
     "cs_db": 5.339,
     "faster": "postgresql",
     "ratio": 2.03,
     "covered": 2476,
     "equivalent": true,
     "replicates": []
    },
    {
     "n": 2000000,
     "pg": 4.008,
     "cs": 7.717,
     "pg_db": 1.719,
     "cs_db": 5.268,
     "faster": "postgresql",
     "ratio": 1.93,
     "covered": 4929,
     "equivalent": true,
     "replicates": [
      {
       "run_id": "20261123T202101Z-main",
       "postgresql": 3.79,
       "cassandra": 8.097,
       "faster": "postgresql",
       "ratio": 2.14
      }
     ]
    }
   ]
  },
  {
   "id": "overview_7d",
   "exp": "E4",
   "label": "Painel 7 dias",
   "class": "agregacao",
   "points": [
    {
     "n": 1000000,
     "pg": 90.783,
     "cs": 6.12,
     "pg_db": 88.063,
     "cs_db": 3.142,
     "faster": "cassandra",
     "ratio": 14.83,
     "covered": 244881,
     "equivalent": true,
     "replicates": []
    },
    {
     "n": 2000000,
     "pg": 173.476,
     "cs": 7.931,
     "pg_db": 170.743,
     "cs_db": 3.635,
     "faster": "cassandra",
     "ratio": 21.87,
     "covered": 489346,
     "equivalent": true,
     "replicates": [
      {
       "run_id": "20261123T202101Z-main",
       "postgresql": 197.558,
       "cassandra": 5.52,
       "faster": "cassandra",
       "ratio": 35.79
      }
     ]
    }
   ]
  },
  {
   "id": "overview_1d",
   "exp": "E4",
   "label": "Painel 1 dia",
   "class": "agregacao",
   "points": [
    {
     "n": 1000000,
     "pg": 17.502,
     "cs": 2.883,
     "pg_db": 15.848,
     "cs_db": 1.536,
     "faster": "cassandra",
     "ratio": 6.07,
     "covered": 48193,
     "equivalent": true,
     "replicates": []
    },
    {
     "n": 2000000,
     "pg": 42.915,
     "cs": 4.391,
     "pg_db": 40.371,
     "cs_db": 2.247,
     "faster": "cassandra",
     "ratio": 9.77,
     "covered": 96707,
     "equivalent": true,
     "replicates": [
      {
       "run_id": "20261123T202101Z-main",
       "postgresql": 44.007,
       "cassandra": 3.892,
       "faster": "cassandra",
       "ratio": 11.31
      }
     ]
    }
   ]
  },
  {
   "id": "overview_7d_alerts",
   "exp": "E4",
   "label": "Painel 7 dias, só alertas",
   "class": "agregacao",
   "points": [
    {
     "n": 1000000,
     "pg": 53.431,
     "cs": 5.905,
     "pg_db": 50.238,
     "cs_db": 3.013,
     "faster": "cassandra",
     "ratio": 9.05,
     "covered": 19758,
     "equivalent": true,
     "replicates": []
    },
    {
     "n": 2000000,
     "pg": 90.429,
     "cs": 5.875,
     "pg_db": 87.846,
     "cs_db": 2.915,
     "faster": "cassandra",
     "ratio": 15.39,
     "covered": 39265,
     "equivalent": true,
     "replicates": [
      {
       "run_id": "20261123T202101Z-main",
       "postgresql": 114.334,
       "cassandra": 6.623,
       "faster": "cassandra",
       "ratio": 17.26
      }
     ]
    }
   ]
  }
 ],
 "control": [
  {
   "logical_events": 1000000,
   "pg_on_read_aggregate_7d": 82.579,
   "pg_mv_read_7d": 1.545,
   "pg_mv_refresh_full": 359.713,
   "cassandra_rollup_db_7d": 3.142
  },
  {
   "logical_events": 2000000,
   "pg_on_read_aggregate_7d": 160.017,
   "pg_mv_read_7d": 1.087,
   "pg_mv_refresh_full": 640.008,
   "cassandra_rollup_db_7d": 3.635
  }
 ],
 "writes": [
  {
   "logical_events": 1000000,
   "config": "padrao",
   "run_id": "20261123T193439Z-main",
   "create": {
    "postgresql": {
     "median_ms": 10.707,
     "ops_s": 670.65
    },
    "cassandra": {
     "median_ms": 8.79,
     "ops_s": 804.3
    }
   },
   "update": {
    "postgresql": {
     "median_ms": 9.377,
     "ops_s": 789.55
    },
    "cassandra": {
     "median_ms": 4.63,
     "ops_s": 1496.5
    }
   },
   "delete": {
    "postgresql": {
     "median_ms": 7.218,
     "ops_s": 933.0
    },
    "cassandra": {
     "median_ms": 6.915,
     "ops_s": 1022.3
    }
   }
  },
  {
   "logical_events": 1000000,
   "config": "antes_do_fsync",
   "run_id": "20261123T193718Z-durability",
   "create": {
    "postgresql": {
     "median_ms": 4.547,
     "ops_s": 1486.0
    },
    "cassandra": {
     "median_ms": 8.17,
     "ops_s": 868.8
    }
   },
   "update": {
    "postgresql": {
     "median_ms": 3.754,
     "ops_s": 1869.6
    },
    "cassandra": {
     "median_ms": 4.665,
     "ops_s": 1536.1
    }
   },
   "delete": {
    "postgresql": {
     "median_ms": 3.083,
     "ops_s": 2174.85
    },
    "cassandra": {
     "median_ms": 6.629,
     "ops_s": 1081.5
    }
   }
  },
  {
   "logical_events": 2000000,
   "config": "padrao",
   "run_id": "20261123T201831Z-main",
   "create": {
    "postgresql": {
     "median_ms": 10.32,
     "ops_s": 675.0
    },
    "cassandra": {
     "median_ms": 7.977,
     "ops_s": 873.8
    }
   },
   "update": {
    "postgresql": {
     "median_ms": 9.869,
     "ops_s": 752.7
    },
    "cassandra": {
     "median_ms": 4.505,
     "ops_s": 1505.65
    }
   },
   "delete": {
    "postgresql": {
     "median_ms": 8.777,
     "ops_s": 857.95
    },
    "cassandra": {
     "median_ms": 6.49,
     "ops_s": 1052.9
    }
   }
  },
  {
   "logical_events": 2000000,
   "config": "antes_do_fsync",
   "run_id": "20261123T202000Z-durability",
   "create": {
    "postgresql": {
     "median_ms": 4.601,
     "ops_s": 1516.9
    },
    "cassandra": {
     "median_ms": 7.853,
     "ops_s": 901.3
    }
   },
   "update": {
    "postgresql": {
     "median_ms": 3.848,
     "ops_s": 1811.9
    },
    "cassandra": {
     "median_ms": 4.476,
     "ops_s": 1541.5
    }
   },
   "delete": {
    "postgresql": {
     "median_ms": 3.135,
     "ops_s": 2093.15
    },
    "cassandra": {
     "median_ms": 6.419,
     "ops_s": 1104.2
    }
   }
  }
 ],
 "storage": [
  {
   "n": 1000000,
   "pg_database_bytes": 799110835,
   "pg_events_bytes": 697516032,
   "cs_keyspace_bytes": 330411810
  },
  {
   "n": 2000000,
   "pg_database_bytes": 1591178931,
   "pg_events_bytes": 1397063680,
   "cs_keyspace_bytes": 662434619
  }
 ],
 "power": [
  {
   "n": 1000000,
   "on_ac_power": false,
   "battery": 62
  },
  {
   "n": 2000000,
   "on_ac_power": false,
   "battery": 26
  }
 ],
 "cache": [
  {
   "n": 1000000,
   "pg": 1.0,
   "cs": 0.9885,
   "disk_read_bytes": {
    "cyberguard-api": 0,
    "cyberguard-postgresql-1": 0,
    "cyberguard-cassandra-1": 0
   }
  },
  {
   "n": 2000000,
   "pg": 1.0,
   "cs": 0.9706,
   "disk_read_bytes": {
    "cyberguard-api": 4000,
    "cyberguard-postgresql-1": 0,
    "cyberguard-cassandra-1": 10000000
   }
  }
 ],
 "loads": [
  {
   "source": "cassandra",
   "target": 1000000,
   "created": 900000,
   "reused": 0,
   "seconds": 1516.36,
   "rate": 593.5,
   "build": "debug",
   "stopped": false,
   "file": "load-cassandra-1000000-20261109T151715Z.json"
  },
  {
   "source": "cassandra",
   "target": 2000000,
   "created": 1000000,
   "reused": 0,
   "seconds": 1318.84,
   "rate": 758.2,
   "build": "release",
   "stopped": false,
   "file": "load-cassandra-2000000-20261123T194438Z.json"
  },
  {
   "source": "postgresql",
   "target": 1000000,
   "created": 900000,
   "reused": 0,
   "seconds": 1716.59,
   "rate": 524.3,
   "build": "debug",
   "stopped": false,
   "file": "load-postgresql-1000000-20261109T144838Z.json"
  },
  {
   "source": "postgresql",
   "target": 2000000,
   "created": 1000000,
   "reused": 0,
   "seconds": 1617.55,
   "rate": 618.2,
   "build": "release",
   "stopped": false,
   "file": "load-postgresql-2000000-20261123T194438Z.json"
  }
 ],
 "validations": {
  "10000": {
   "passed": 22,
   "total": 22,
   "file": "validate-10000-20261109T144039Z.json",
   "seconds": 23.6
  },
  "100000": {
   "passed": 22,
   "total": 22,
   "file": "validate-100000-20261109T144814Z.json",
   "seconds": 37.6
  },
  "1000000": {
   "passed": 22,
   "total": 22,
   "file": "validate-1000000-20261123T192730Z.json",
   "seconds": 185.2
  },
  "2000000": {
   "passed": 22,
   "total": 22,
   "file": "validate-2000000-20261123T201732Z.json",
   "seconds": 346.0
  }
 },
 "rollups": [
  {
   "events": 1000024,
   "cells": 9978,
   "deltas": 0,
   "pg_equal": true,
   "file": "rollup-check-20261123T192828Z.json"
  },
  {
   "events": 2000024,
   "cells": 10092,
   "deltas": 0,
   "pg_equal": true,
   "file": "rollup-check-20261123T201826Z.json"
  }
 ],
 "runs": {
  "1000000": {
   "main": "20261123T193439Z-main",
   "durability": "20261123T193718Z-durability"
  },
  "2000000": {
   "main": "20261123T201831Z-main",
   "durability": "20261123T202000Z-durability"
  }
 }
};
