-- Skjema for Tyholt Pizzeria. Kjøres idempotent ved oppstart (app/db.py).
-- Alle beløp er heltall øre — aldri float på penger.
-- Alle tidspunkt er ISO-8601 med tidssone, lagret som TEXT.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── Allergener ──────────────────────────────────────────────────────────────
-- Fast vokabular: de 14 deklarasjonspliktige kategoriene etter
-- matinformasjonsforskriften / EU 1169/2011 vedlegg II. Rader seedes i
-- app/allergener.py og skal ikke utvides med egne kategorier.
CREATE TABLE IF NOT EXISTS allergen (
    kode        TEXT PRIMARY KEY,
    navn        TEXT NOT NULL,
    presisering TEXT NOT NULL DEFAULT '',
    rekkefolge  INTEGER NOT NULL
);

-- En råvare slik den faktisk står på pakka.
-- verifisert = 0 betyr «ikke lest av på emballasjen ennå» og vises som
-- uverifisert i admin, slik at ingen tror allergenlista er kvalitetssikret.
CREATE TABLE IF NOT EXISTS ingrediens (
    id         INTEGER PRIMARY KEY,
    navn       TEXT NOT NULL UNIQUE,
    notat      TEXT NOT NULL DEFAULT '',
    verifisert INTEGER NOT NULL DEFAULT 0 CHECK (verifisert IN (0, 1))
);

CREATE TABLE IF NOT EXISTS ingrediens_allergen (
    ingrediens_id INTEGER NOT NULL REFERENCES ingrediens(id) ON DELETE CASCADE,
    allergen_kode TEXT    NOT NULL REFERENCES allergen(kode),
    PRIMARY KEY (ingrediens_id, allergen_kode)
);

-- ── Meny ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS menyelement (
    id           INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,
    navn         TEXT NOT NULL,
    -- Kort navn til etiketten. 12 mm tape har lite plass, så «Pære» slår
    -- «Hvit pizza med pære» når kokken skal lese den på tvers av bordet.
    etikettnavn  TEXT NOT NULL,
    beskrivelse  TEXT NOT NULL DEFAULT '',
    pris_ore     INTEGER NOT NULL CHECK (pris_ore >= 0),
    rekkefolge   INTEGER NOT NULL DEFAULT 0,
    tilgjengelig INTEGER NOT NULL DEFAULT 1 CHECK (tilgjengelig IN (0, 1)),
    opprettet    TEXT NOT NULL,
    oppdatert    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS menyelement_ingrediens (
    menyelement_id INTEGER NOT NULL REFERENCES menyelement(id) ON DELETE CASCADE,
    ingrediens_id  INTEGER NOT NULL REFERENCES ingrediens(id),
    rekkefolge     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (menyelement_id, ingrediens_id)
);

-- ── Salgsdager ──────────────────────────────────────────────────────────────
-- Egen tabell framfor kalenderdato, fordi åpningstiden 15:00–00:00 ikke
-- nødvendigvis stopper ved midnatt. Dagsnummer nullstilles per salgsdag,
-- og en ekstra dag er én rad.
-- startnummer: dagens forste ordre far dette nummeret framfor 1. Et tosifret
-- starttall ser ut som vi har holdt pa en stund, og koster ingenting.
CREATE TABLE IF NOT EXISTS salgsdag (
    id          INTEGER PRIMARY KEY,
    dato        TEXT NOT NULL UNIQUE,
    apner       TEXT NOT NULL,
    stenger     TEXT NOT NULL,
    aktiv       INTEGER NOT NULL DEFAULT 1 CHECK (aktiv IN (0, 1)),
    startnummer INTEGER NOT NULL DEFAULT 1
);

-- ── Ordrer ──────────────────────────────────────────────────────────────────
-- id er internt. dagsnummer er det kunden får ropt opp, unikt per salgsdag.
-- betalt er egen kolonne, ikke en status: betaling skjer på Vipps utenfor
-- systemet og bekreftes ved henting, så den er ortogonal til produksjonsløpet.
CREATE TABLE IF NOT EXISTS ordre (
    id          INTEGER PRIMARY KEY,
    salgsdag_id INTEGER NOT NULL REFERENCES salgsdag(id),
    dagsnummer  INTEGER NOT NULL,
    kundenavn   TEXT NOT NULL,
    epost       TEXT,
    status      TEXT NOT NULL DEFAULT 'ny'
                CHECK (status IN ('ny', 'i_produksjon', 'klar', 'levert', 'forlatt', 'avbrutt')),
    betalt      INTEGER NOT NULL DEFAULT 0 CHECK (betalt IN (0, 1)),
    total_ore   INTEGER NOT NULL CHECK (total_ore >= 0),
    notat       TEXT NOT NULL DEFAULT '',
    opprettet   TEXT NOT NULL,
    oppdatert   TEXT NOT NULL,
    UNIQUE (salgsdag_id, dagsnummer)
);

-- navn og pris kopieres inn ved bestilling. Endrer vi menyen midt i kvelden
-- skal gamle ordrer fortsatt vise det kunden faktisk bestilte og betalte.
CREATE TABLE IF NOT EXISTS ordrelinje (
    id                INTEGER PRIMARY KEY,
    ordre_id          INTEGER NOT NULL REFERENCES ordre(id) ON DELETE CASCADE,
    menyelement_id    INTEGER NOT NULL REFERENCES menyelement(id),
    navn_snapshot     TEXT    NOT NULL,
    etikett_snapshot  TEXT    NOT NULL,
    pris_ore_snapshot INTEGER NOT NULL CHECK (pris_ore_snapshot >= 0),
    antall            INTEGER NOT NULL CHECK (antall > 0)
);

CREATE INDEX IF NOT EXISTS idx_ordrelinje_ordre ON ordrelinje(ordre_id);
CREATE INDEX IF NOT EXISTS idx_ordre_status     ON ordre(status);
CREATE INDEX IF NOT EXISTS idx_ordre_salgsdag   ON ordre(salgsdag_id, dagsnummer);

-- Revisjonsspor. Når noe går galt en travel kveld vil vi kunne se hvem som
-- flyttet hva, og når.
CREATE TABLE IF NOT EXISTS statuslogg (
    id         INTEGER PRIMARY KEY,
    ordre_id   INTEGER NOT NULL REFERENCES ordre(id) ON DELETE CASCADE,
    fra_status TEXT,
    til_status TEXT NOT NULL,
    aktor      TEXT NOT NULL DEFAULT 'admin',
    opprettet  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_statuslogg_ordre ON statuslogg(ordre_id);

-- ── Jobbkø ──────────────────────────────────────────────────────────────────
-- Etikettprint og e-post går gjennom samme tabell, men har hver sin arbeider
-- (app/jobber.py). En sovende printer kan henge i det uendelige, og skal ikke
-- kunne stoppe utgående e-post.
CREATE TABLE IF NOT EXISTS jobb (
    id         INTEGER PRIMARY KEY,
    type       TEXT NOT NULL CHECK (type IN ('etikett', 'epost')),
    nyttelast  TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'ny'
               CHECK (status IN ('ny', 'kjorer', 'ferdig', 'feilet')),
    forsok     INTEGER NOT NULL DEFAULT 0,
    siste_feil TEXT NOT NULL DEFAULT '',
    ordre_id   INTEGER REFERENCES ordre(id) ON DELETE CASCADE,
    opprettet  TEXT NOT NULL,
    oppdatert  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobb_ko    ON jobb(type, status, id);
CREATE INDEX IF NOT EXISTS idx_jobb_ordre ON jobb(ordre_id);

-- ── Vipps-mottakere ─────────────────────────────────────────────────────────
-- Hvem som tar imot betalingen skal kunne rulleres midt i en kveld. Egen
-- tabell framfor to felt, fordi det er en LISTE man velger fra - da slipper
-- man a skrive inn et attensifret nummer riktig mens det staar folk i kassa.
--
-- Betalingslenken lagres ikke: den er deterministisk ut fra nummeret, og et
-- utledet felt kan ikke komme i utakt med kilden sin.
CREATE TABLE IF NOT EXISTS vipps_mottaker (
    id         INTEGER PRIMARY KEY,
    navn       TEXT NOT NULL,
    nummer     TEXT NOT NULL UNIQUE,
    rekkefolge INTEGER NOT NULL DEFAULT 0
);

-- ── Innstillinger ───────────────────────────────────────────────────────────
-- Nøkkel/verdi for det som må kunne endres uten deploy: Vipps-mottaker,
-- manuell stengt-bryter, global spor-liste.
CREATE TABLE IF NOT EXISTS innstilling (
    nokkel    TEXT PRIMARY KEY,
    verdi     TEXT NOT NULL,
    oppdatert TEXT NOT NULL
);
