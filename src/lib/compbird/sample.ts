/**
 * The sample dossier painted on first load + used as the live-failure fallback.
 * REAL DATA (2026-07-02): a verbatim engine run for 1203 Walnut Ridge Road,
 * Christiansburg (parcel 230322) — real comps, real methods, real market
 * context — so the landing's figures and the studio's sample are ACCURATE, not
 * fabricated. Regenerate by POSTing /api/compbird/profile {parcelId:"230322"}
 * and pasting the JSON here (see docs). SAMPLE_MARKETS are likewise a real
 * /api/compbird/markets snapshot.
 */
import type { ProfileResult, NeighborhoodMarket, PropertyMatch } from "./types";

export const SAMPLE_PROFILE: ProfileResult = {
  "ok": true,
  "facts": {
    "address": "1203 Walnut Ridge Road",
    "city": "Christiansburg",
    "county": "Montgomery",
    "parcel_id": "230322",
    "subdivision": "Walnut Creek",
    "property_type": "RE_1",
    "status": "Active",
    "sqft": 2096,
    "acres": 0.257,
    "beds": 4,
    "full_baths": 3,
    "half_baths": 1,
    "year_built": 2022,
    "assessed_value": 367700,
    "lat": 37.148417,
    "lng": -80.364988,
    "list_price": 498000
  },
  "valuation": {
    "mid": 455000,
    "low": 400000,
    "high": 520000,
    "comp_ppsf": 220.4,
    "implied_subject_ppsf": 217.1,
    "divergence_pct": 6.5,
    "methods": [
      {
        "name": "Prior sale + trend",
        "value": null,
        "rationale": "No MLS-confirmed prior sale (assessor deeds are not trusted as anchors)."
      },
      {
        "name": "Direct comp + acreage adjustment",
        "value": 442537,
        "rationale": "Top 3 comps (1461 Walnut Ridge Road / 1041 ST CLAIR Lane / 1441 Walnut Ridge Road) median time+size-adj $211/sf × 2,096 sqft = $443k = <b>$443k</b>."
      },
      {
        "name": "$/sqft",
        "value": 459467,
        "rationale": "Median time+size-adjusted $219/sf × 2,096 sqft = <b>$459k</b>."
      },
      {
        "name": "Acreage residual",
        "value": 472200,
        "rationale": "Comp improvement avg $220/sf; residual land rate $40,242/eff-ac. 2,096 sqft + 0.3 ac (≈0.3 eff-ac) → <b>$472k</b>."
      },
      {
        "name": "AVM (model)",
        "value": null,
        "rationale": "Skipped (fast / interactive mode)."
      }
    ]
  },
  "comps": [
    {
      "address": "1461 Walnut Ridge Road",
      "city": "Christiansburg",
      "subdivision": "Walnut Creek",
      "sold_price": 444800,
      "ppsf": 219.8,
      "sqft": 2024,
      "acres": 0.75,
      "beds": 4,
      "baths": 2,
      "year_built": 2026,
      "close_date": "2026-06-09",
      "dom": 96,
      "distance_mi": 0.2,
      "lat": 37.150885,
      "lng": -80.36295,
      "pending": false,
      "atypical": false
    },
    {
      "address": "1041 ST CLAIR Lane",
      "city": "Christiansburg",
      "subdivision": "Walnut Creek",
      "sold_price": 400000,
      "ppsf": 192.8,
      "sqft": 2075,
      "acres": 0.3,
      "beds": 4,
      "baths": 2,
      "year_built": 2018,
      "close_date": "2026-04-17",
      "dom": 3,
      "distance_mi": 0.09,
      "lat": 37.147482,
      "lng": -80.363748,
      "pending": false,
      "atypical": false
    },
    {
      "address": "1441 Walnut Ridge Road",
      "city": "Christiansburg",
      "subdivision": "Walnut Creek",
      "sold_price": 460000,
      "ppsf": 208.4,
      "sqft": 2207,
      "acres": 0.48,
      "beds": 5,
      "baths": 2,
      "year_built": 2026,
      "close_date": "2026-06-22",
      "dom": 119,
      "distance_mi": 0.2,
      "lat": 37.150588,
      "lng": -80.362581,
      "pending": false,
      "atypical": false
    },
    {
      "address": "1140 Crosscreek Drive",
      "city": "Christiansburg",
      "subdivision": "Walnut Creek",
      "sold_price": 460000,
      "ppsf": 220.9,
      "sqft": 2082,
      "acres": 0.46,
      "beds": 4,
      "baths": 3,
      "year_built": 2018,
      "close_date": "2025-04-14",
      "dom": 65,
      "distance_mi": 0.11,
      "lat": 37.146968,
      "lng": -80.364234,
      "pending": false,
      "atypical": false
    },
    {
      "address": "1271 WALNUT RIDGE Road",
      "city": "Christiansburg",
      "subdivision": "Walnut Creek",
      "sold_price": 490000,
      "ppsf": 230.7,
      "sqft": 2124,
      "acres": 0.27,
      "beds": 4,
      "baths": 2,
      "year_built": 2020,
      "close_date": "2024-06-10",
      "dom": 0,
      "distance_mi": 0.1,
      "lat": 37.148531,
      "lng": -80.363158,
      "pending": false,
      "atypical": false
    },
    {
      "address": "1031 GREEN RIDGE Road",
      "city": "Christiansburg",
      "subdivision": "Walnut Creek",
      "sold_price": 550000,
      "ppsf": 252.1,
      "sqft": 2182,
      "acres": 0.3,
      "beds": 5,
      "baths": 3,
      "year_built": 2009,
      "close_date": "2025-12-12",
      "dom": 62,
      "distance_mi": 0.33,
      "lat": 37.146554,
      "lng": -80.359564,
      "pending": false,
      "atypical": false
    }
  ],
  "saleHistory": [],
  "marketContext": {
    "scope": "subdivision",
    "scope_value": "WALNUT CREEK",
    "sold_count": 9,
    "median_ppsf": 216.4,
    "median_sold_price": 456900,
    "median_dom": 62,
    "active_count": 14,
    "months_of_inventory": 18.7,
    "ppsf_trend_pct": -1.1,
    "ppsf_median": 216.4,
    "ppsf_trend": -1.1,
    "ppsf_trend_direction": "down"
  },
  "meta": {
    "generated": "2026-07-02T16:57:41+00:00",
    "as_of": "2026-07-02",
    "flags": null
  }
};

export const SAMPLE_PRESETS: PropertyMatch[] = [
  {
    source: "mls",
    address: "1203 Walnut Ridge Road, Christiansburg, VA 24073",
    city: "Christiansburg",
    county: "Montgomery",
    parcel_id: "230322",
    sqft: 2096,
    bedrooms: 4,
    status: "Closed",
  },
  {
    source: "mls",
    address: "114 Orchard Drive, Narrows, VA 24124",
    city: "Narrows",
    county: "Giles",
    parcel_id: "8247",
    sqft: 2433,
    bedrooms: 3,
    status: "Closed",
  },
  {
    source: "mls",
    address: "680 Liberty Viaduct, Christiansburg, VA 24073",
    city: "Christiansburg",
    county: "Montgomery",
    parcel_id: "027172",
    sqft: 1404,
    bedrooms: 3,
    status: "Closed",
  },
];

export const SAMPLE_MARKETS: NeighborhoodMarket[] = [
  {
    "name": "The Preserve",
    "area": "Blacksburg, Montgomery County",
    "medianPrice": 474009,
    "ppsf": 272,
    "ppsfTrendPct": -5.3,
    "medianDom": 21,
    "monthsOfInventory": 2,
    "soldCount": 48,
    "activeCount": 8,
    "trend": [
      534445,
      681356,
      792942,
      823399,
      721393,
      613690,
      530528,
      410475,
      425507,
      368229,
      385229,
      360000
    ],
    "note": "Tight supply favors sellers; a typical sale takes about 21 days."
  },
  {
    "name": "Oak Tree",
    "area": "Christiansburg, Montgomery County",
    "medianPrice": 275000,
    "ppsf": 193,
    "ppsfTrendPct": 5.1,
    "medianDom": 6,
    "monthsOfInventory": 1.4,
    "soldCount": 43,
    "activeCount": 5,
    "trend": [
      267500,
      264917,
      254250,
      265083,
      270833,
      278833,
      275333,
      268817,
      267817,
      272117,
      281267,
      284900
    ],
    "note": "Tight supply favors sellers; homes clear in under two weeks."
  },
  {
    "name": "Herons Landing",
    "area": "Radford, Pulaski County",
    "medianPrice": 627450,
    "ppsf": 245,
    "ppsfTrendPct": -11.4,
    "medianDom": 103,
    "monthsOfInventory": 3,
    "soldCount": 16,
    "activeCount": 4,
    "trend": [
      513475,
      517317,
      527483,
      561667,
      615000,
      668333,
      654150,
      637450,
      617450,
      628300,
      625000,
      625000
    ],
    "note": "Supply and demand are balanced; listings sit ~103 days before closing."
  },
  {
    "name": "Highland Park",
    "area": "Narrows, Giles County",
    "medianPrice": 249250,
    "ppsf": 237,
    "ppsfTrendPct": 20.4,
    "medianDom": 5,
    "monthsOfInventory": 0.8,
    "soldCount": 16,
    "activeCount": 1,
    "trend": [
      275000,
      267000,
      270667,
      251000,
      251000,
      250167,
      253833,
      265333,
      278767,
      271683,
      256767,
      240750
    ],
    "note": "Tight supply favors sellers; homes clear in under two weeks."
  },
  {
    "name": "Midtown",
    "area": "Blacksburg, Montgomery County",
    "medianPrice": 761151,
    "ppsf": 346,
    "ppsfTrendPct": 3.9,
    "medianDom": 15,
    "monthsOfInventory": 7.2,
    "soldCount": 15,
    "activeCount": 9,
    "trend": [
      812000,
      769715,
      748082,
      745169,
      787454,
      809087,
      961333,
      1110667,
      1131667,
      1003333,
      875000,
      875000
    ],
    "note": "Ample supply favors buyers; a typical sale takes about 15 days."
  },
  {
    "name": "The Village at Tom's Creek",
    "area": "Blacksburg, Montgomery County",
    "medianPrice": 495000,
    "ppsf": 270,
    "ppsfTrendPct": -9.3,
    "medianDom": 47,
    "monthsOfInventory": 3.2,
    "soldCount": 15,
    "activeCount": 4,
    "trend": [
      495000,
      477333,
      512333,
      513667,
      532667,
      496000,
      493000,
      502417,
      514833,
      556500,
      585750,
      615000
    ],
    "note": "Supply and demand are balanced; listings sit ~47 days before closing."
  }
];
