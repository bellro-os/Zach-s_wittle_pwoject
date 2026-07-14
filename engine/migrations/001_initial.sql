CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE properties (
    parcel_id           text PRIMARY KEY,
    tax_map_id          text,
    jurisdiction        text,
    site_addr1          text,
    site_addr2          text,
    mail_addr1          text,
    mail_addr2          text,
    owner1              text,
    owner2              text,
    assessed_total      numeric,
    assessed_land       numeric,
    assessed_bldg       numeric,
    last_sale_date      date,
    last_sale_price     numeric,
    acres               numeric,
    year_built          int,
    bedrooms            int,
    full_baths          int,
    half_baths          int,
    sfla                int,
    stories             numeric,
    zoning              text,
    subd_name           text,
    neighborhood        text,
    deedbook            text,
    deedpage            text,
    geom                geometry(MultiPolygon, 4326),
    centroid            geometry(Point, 4326),
    raw                 jsonb NOT NULL,
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX properties_jurisdiction_idx  ON properties (jurisdiction);
CREATE INDEX properties_mail_addr_idx     ON properties (mail_addr1);
CREATE INDEX properties_last_sale_idx     ON properties (last_sale_date);
CREATE INDEX properties_centroid_gix      ON properties USING GIST (centroid);

CREATE TABLE listings (
    listing_id          text PRIMARY KEY,
    list_key            text,
    mls_number          text,
    status              text NOT NULL,
    status_changed_at   timestamptz,
    list_price          numeric,
    original_list_price numeric,
    sold_price          numeric,
    list_date           date,
    expiration_date     date,
    close_date          date,
    dom                 int,
    property_type       text,
    bedrooms            int,
    full_baths          int,
    half_baths          int,
    sqft                int,
    year_built          int,
    site_addr           text,
    city                text,
    state               text,
    zip                 text,
    list_agent_key      text,
    list_office_key     text,
    public_remarks      text,
    parcel_id           text REFERENCES properties(parcel_id),
    raw                 jsonb NOT NULL,
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX listings_status_idx       ON listings (status);
CREATE INDEX listings_city_idx         ON listings (city);
CREATE INDEX listings_status_changed   ON listings (status_changed_at DESC);
CREATE INDEX listings_parcel_idx       ON listings (parcel_id);

CREATE TABLE listing_history (
    id                  bigserial PRIMARY KEY,
    listing_id          text NOT NULL REFERENCES listings(listing_id) ON DELETE CASCADE,
    status              text NOT NULL,
    list_price          numeric,
    observed_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX listing_history_listing_idx ON listing_history (listing_id, observed_at DESC);

CREATE TABLE leads (
    id                  bigserial PRIMARY KEY,
    category            text NOT NULL,
    parcel_id           text REFERENCES properties(parcel_id),
    listing_id          text REFERENCES listings(listing_id),
    score               int,
    detail              jsonb NOT NULL,
    status              text NOT NULL DEFAULT 'new',
    notes               text,
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (parcel_id IS NOT NULL OR listing_id IS NOT NULL)
);
CREATE UNIQUE INDEX leads_unique_idx ON leads (category, coalesce(parcel_id,''), coalesce(listing_id,''));
CREATE INDEX leads_status_idx        ON leads (status);
CREATE INDEX leads_first_seen_idx    ON leads (first_seen_at DESC);
