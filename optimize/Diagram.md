# 🗂️ SCHÉMA DES TABLES - INVENTORY DJANGO

## 📊 VUE D’ENSEMBLE SIMPLIFIÉE

```
┌─────────────────────────────────────────────────────────────────┐
│                     TABLES DE PRODUCTION                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────┐         ┌──────────────────────────┐  │
│  │      Server         │         │  ServerGroupSummary      │  │
│  ├─────────────────────┤         ├──────────────────────────┤  │
│  │ • id (PK)           │         │ • id (PK)                │  │
│  │ • SERVER_ID ◄───────┼─────────┼─► SERVER_ID (unique)     │  │
│  │ • PAMELA_ENV        │  Lien   │ • total_instances        │  │
│  │ • PAMELA_DC         │ logique │ • constant_fields (JSON) │  │
│  │ • APP_NAME_VALUE    │ (pas FK)│ • variable_fields (JSON) │  │
│  │ • ... (70+ champs)  │         │ • last_updated           │  │
│  └─────────────────────┘         └──────────────────────────┘  │
│           │                                                     │
│           │ Lien logique                                        │
│           │ (pas FK)                                            │
│           ▼                                                     │
│  ┌─────────────────────┐                                       │
│  │  ServerAnnotation   │                                       │
│  ├─────────────────────┤                                       │
│  │ • id (PK)           │                                       │
│  │ • SERVER_ID (unique)│                                       │
│  │ • notes             │                                       │
│  │ • type              │                                       │
│  │ • servicenow        │                                       │
│  │ • history (JSON)    │                                       │
│  │ • updated_at        │                                       │
│  └─────────────────────┘                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      TABLES DE STAGING                          │
│                    (Pendant l'import)                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────┐         ┌──────────────────────────┐  │
│  │   ServerStaging     │         │ServerGroupSummaryStaging │  │
│  ├─────────────────────┤         ├──────────────────────────┤  │
│  │ • Mêmes champs que  │         │ • Mêmes champs que       │  │
│  │   Server            │         │   ServerGroupSummary     │  │
│  │ • managed = False   │         │ • managed = False        │  │
│  └─────────────────────┘         └──────────────────────────┘  │
│           │                                │                    │
│           └────────────┬───────────────────┘                    │
│                        │                                        │
│                        │ Après validation                       │
│                        ▼                                        │
│              DROP + RENAME vers                                 │
│           tables de production ⬆️                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      TABLE AUXILIAIRE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────┐                                       │
│  │   ImportStatus      │                                       │
│  ├─────────────────────┤                                       │
│  │ • id (PK)           │                                       │
│  │ • date_import       │                                       │
│  │ • success           │                                       │
│  │ • message           │                                       │
│  │ • nb_entries_created│                                       │
│  │ • nb_groups_created │                                       │
│  │ • source_url        │                                       │
│  └─────────────────────┘                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

-----

## 🔄 WORKFLOW D’IMPORT DÉTAILLÉ

```
ÉTAPE 1 : État Initial (Avant Import)
═════════════════════════════════════

┌──────────────────┐          ┌─────────────────────────┐
│     Server       │          │  ServerGroupSummary     │
│  (400k lignes)   │◄────────►│     (200k lignes)       │
│   Avec indexes   │  Lien    │     Avec indexes        │
└──────────────────┘ logique  └─────────────────────────┘
        │
        │ Lien logique
        ▼
┌──────────────────┐
│ServerAnnotation  │
│   (5k lignes)    │
└──────────────────┘


ÉTAPE 2 : Création des tables Staging
═════════════════════════════════════

┌──────────────────┐          ┌─────────────────────────┐
│     Server       │          │  ServerGroupSummary     │
│  (400k lignes)   │          │     (200k lignes)       │
│   Avec indexes   │          │     Avec indexes        │
└──────────────────┘          └─────────────────────────┘
        │                              │
        │ CREATE TABLE ... LIKE        │ CREATE TABLE ... LIKE
        │ (copie structure + indexes)  │ (copie structure + indexes)
        ▼                              ▼
┌──────────────────┐          ┌─────────────────────────┐
│  ServerStaging   │          │ServerGroupSummaryStaging│
│    (0 ligne)     │          │       (0 ligne)         │
│   Avec indexes ✅ │          │     Avec indexes ✅      │
└──────────────────┘          └─────────────────────────┘


ÉTAPE 3 : Remplissage des Staging
═════════════════════════════════

                 ┌─────────────────┐
                 │   Import CSV    │
                 │  (Nouvelle data)│
                 └─────────────────┘
                          │
                          │ INSERT
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
┌──────────────────┐          ┌─────────────────────────┐
│  ServerStaging   │          │ServerGroupSummaryStaging│
│  (410k lignes)   │◄────────►│     (210k lignes)       │
│   Avec indexes   │  Calcul  │     Avec indexes        │
│   ✅ REMPLIE     │  Summary │     ✅ REMPLIE          │
└──────────────────┘          └─────────────────────────┘

┌──────────────────┐          ┌─────────────────────────┐
│     Server       │          │  ServerGroupSummary     │
│  (400k lignes)   │          │     (200k lignes)       │
│ ⚠️ ANCIENNE DATA │          │   ⚠️ ANCIENNE DATA      │
└──────────────────┘          └─────────────────────────┘


ÉTAPE 4 : Swap Atomique (DROP + RENAME)
════════════════════════════════════════

                    ┌─────────────┐
                    │ Validation  │
                    │  Import OK? │
                    └──────┬──────┘
                           │ OUI
                           ▼
              ┌────────────────────────┐
              │ 1. DROP TABLE Server   │
              │ 2. RENAME Staging → Server│
              └────────────────────────┘
                           │
                           ▼
                  Tables swappées ! ✅

┌──────────────────┐          ┌─────────────────────────┐
│     Server       │          │  ServerGroupSummary     │
│  (410k lignes)   │◄────────►│     (210k lignes)       │
│ ✅ NOUVELLE DATA │  Lien    │   ✅ NOUVELLE DATA      │
│   Avec indexes   │ logique  │     Avec indexes        │
└──────────────────┘          └─────────────────────────┘
        │
        │ Lien logique (conservé)
        ▼
┌──────────────────┐
│ServerAnnotation  │
│   (5k lignes)    │
│ ✅ Préservée     │
└──────────────────┘
```

-----

## 🔗 RELATIONS ENTRE LES TABLES

### Relation Server ↔ ServerGroupSummary

```
┌─────────────────────────────────────────────────────────────────┐
│                   RELATION LOGIQUE (Pas de FK)                  │
└─────────────────────────────────────────────────────────────────┘

Server (table détaillée)              ServerGroupSummary (résumé)
═══════════════════════                ═══════════════════════════
SERVER_ID: "SRV001"                    SERVER_ID: "SRV001"
APP_NAME: "AppA"           ┐           total_instances: 3
PAMELA_ENV: "PROD"         │           constant_fields: {
...                        │             "PAMELA_ENV": "PROD",
                           │             "PAMELA_DC": "DC1"
SERVER_ID: "SRV001"        ├──────►    }
APP_NAME: "AppB"           │           variable_fields: {
PAMELA_ENV: "PROD"         │             "APP_NAME": {
...                        │               "count": 3,
                           │               "preview": "AppA | AppB | AppC"
SERVER_ID: "SRV001"        │             }
APP_NAME: "AppC"           │           }
PAMELA_ENV: "PROD"         │           last_updated: 2025-11-14
...                        ┘

┌────────────────────────────────────────────────────────────────┐
│ Lien : Server.SERVER_ID == ServerGroupSummary.SERVER_ID        │
│ Type : Relation logique (CharField), pas de ForeignKey        │
│ Cardinalité : N:1 (Plusieurs Server → Une Summary)            │
└────────────────────────────────────────────────────────────────┘
```

### Relation Server ↔ ServerAnnotation

```
┌─────────────────────────────────────────────────────────────────┐
│                   RELATION LOGIQUE (Pas de FK)                  │
└─────────────────────────────────────────────────────────────────┘

Server (n occurrences)            ServerAnnotation (1 occurrence)
═══════════════════                ═══════════════════════════════
SERVER_ID: "SRV001"                SERVER_ID: "SRV001"
APP_NAME: "AppA"                   notes: "À patcher en urgence"
...                    ┐           type: "maintenance"
                       ├──────►    servicenow: "RITM0012345"
SERVER_ID: "SRV001"    │           history: [
APP_NAME: "AppB"       │             {
...                    │               "text": "Patch planifié",
                       │               "user": "john.doe",
SERVER_ID: "SRV001"    │               "date": "2025-11-10",
APP_NAME: "AppC"       │             },
...                    ┘             ...
                                   ]

┌────────────────────────────────────────────────────────────────┐
│ Lien : Server.SERVER_ID == ServerAnnotation.SERVER_ID          │
│ Type : Relation logique (CharField), pas de ForeignKey        │
│ Cardinalité : N:1 (Plusieurs Server → Une Annotation)         │
│ Particularité : Annotation UNIQUE par hostname, persiste      │
│                 même si Server est droppé/réimporté            │
└────────────────────────────────────────────────────────────────┘
```

-----

## 📋 CARDINALITÉS DÉTAILLÉES

```
┌──────────────────────────────────────────────────────────────────┐
│                        CARDINALITÉS                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Server (1 serveur physique/virtuel)                            │
│    ├─► Peut avoir N occurrences dans la table (N applis)       │
│    ├─► Appartient à 1 ServerGroupSummary (résumé)              │
│    └─► Peut avoir 0 ou 1 ServerAnnotation                      │
│                                                                  │
│  ServerGroupSummary (1 résumé par hostname)                     │
│    ├─► Résume N occurrences de Server avec même hostname       │
│    └─► Relation 1:N avec Server                                │
│                                                                  │
│  ServerAnnotation (1 annotation par hostname)                   │
│    ├─► Concerne N occurrences de Server avec même hostname     │
│    └─► Relation 1:N avec Server                                │
│                                                                  │
│  ImportStatus (1 entrée par import)                             │
│    └─► Pas de relation avec les autres tables                  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

-----

## 🎯 EXEMPLE CONCRET

### Données dans Server

```sql
SELECT SERVER_ID, APP_NAME_VALUE, PAMELA_ENVIRONMENT 
FROM Server 
WHERE SERVER_ID = 'SRVPROD123'
ORDER BY APP_NAME_VALUE;

┌─────────────┬──────────────────┬──────────────────┐
│ SERVER_ID   │ APP_NAME_VALUE   │ PAMELA_ENVIRONMENT│
├─────────────┼──────────────────┼──────────────────┤
│ SRVPROD123  │ ApplicationWeb   │ PROD             │
│ SRVPROD123  │ DatabaseOracle   │ PROD             │
│ SRVPROD123  │ MonitoringAgent  │ PROD             │
└─────────────┴──────────────────┴──────────────────┘
                    3 lignes
```

### Données dans ServerGroupSummary

```sql
SELECT SERVER_ID, total_instances, constant_fields, variable_fields
FROM ServerGroupSummary
WHERE SERVER_ID = 'SRVPROD123';

┌─────────────┬─────────────────┬──────────────────────┬─────────────────────┐
│ SERVER_ID   │ total_instances │ constant_fields      │ variable_fields     │
├─────────────┼─────────────────┼──────────────────────┼─────────────────────┤
│ SRVPROD123  │ 3               │ {                    │ {                   │
│             │                 │   "PAMELA_ENVIRONMENT│   "APP_NAME_VALUE": {│
│             │                 │    ": "PROD",        │     "count": 3,     │
│             │                 │   "PAMELA_DC":       │     "preview":      │
│             │                 │    "DC1",            │     "ApplicationWeb │
│             │                 │   ...                │     | DatabaseOracle│
│             │                 │ }                    │     | Monitoring..."│
│             │                 │                      │   }                 │
│             │                 │                      │ }                   │
└─────────────┴─────────────────┴──────────────────────┴─────────────────────┘
                                     1 ligne
```

### Données dans ServerAnnotation

```sql
SELECT SERVER_ID, notes, type, servicenow
FROM ServerAnnotation
WHERE SERVER_ID = 'SRVPROD123';

┌─────────────┬─────────────────────────────┬─────────────┬──────────────┐
│ SERVER_ID   │ notes                       │ type        │ servicenow   │
├─────────────┼─────────────────────────────┼─────────────┼──────────────┤
│ SRVPROD123  │ Serveur critique - Patch    │ maintenance │ RITM0045678  │
│             │ mensuel requis              │             │              │
└─────────────┴─────────────────────────────┴─────────────┴──────────────┘
                                  1 ligne (ou 0 si pas d'annotation)
```

-----

## 🔍 INDEXES PAR TABLE

```
┌──────────────────────────────────────────────────────────────────┐
│                       INDEXES SUR Server                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  📌 Index Primaire (auto)                                        │
│     • id (PK)                                                    │
│                                                                  │
│  📌 Indexes Simples (existants + nouveaux)                       │
│     • SERVER_ID                     ← Recherche par hostname     │
│     • PAMELA_OSSHORTNAME            ← Filtrage OS                │
│     • PAMELA_SERIAL                 ← Recherche hardware         │
│     • PAMELA_MODEL                  ← Filtrage modèle            │
│     • PAMELA_PRODUCT                ← Filtrage produit           │
│     • SERVER_DATACENTER_VALUE       ← Filtrage datacenter        │
│     • PAMELA_ENVIRONMENT       ✨ NEW ← Filtrage environnement   │
│     • PAMELA_AREA              ✨ NEW ← Filtrage zone            │
│     • PAMELA_DATACENTER        ✨ NEW ← Filtrage DC (autre champ)│
│     • PAMELA_SNOWITG_STATUS    ✨ NEW ← Filtrage statut          │
│                                                                  │
│  📌 Index Composé (nouveau)                                      │
│     • (SERVER_ID, APP_NAME_VALUE) ✨ NEW                         │
│       → Optimise les GROUP BY hostname avec filtre sur app      │
│                                                                  │
│  💡 Total : ~12 indexes                                          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                 INDEXES SUR ServerGroupSummary                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  📌 Index Primaire (auto)                                        │
│     • id (PK)                                                    │
│                                                                  │
│  📌 Index Unique (existant + amélioré)                           │
│     • SERVER_ID (unique, db_index=True)                          │
│       → Recherche rapide du résumé par hostname                 │
│                                                                  │
│  📌 Indexes Simples (nouveaux)                                   │
│     • last_updated             ✨ NEW                            │
│       → Tri par date de MAJ, trouve résumés obsolètes           │
│     • total_instances          ✨ NEW                            │
│       → Filtre serveurs avec N occurrences                      │
│                                                                  │
│  📌 Index Composé (nouveau)                                      │
│     • (SERVER_ID, total_instances) ✨ NEW                        │
│       → Optimise recherche + comptage                           │
│                                                                  │
│  💡 Total : ~5 indexes                                           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                  INDEXES SUR ServerAnnotation                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  📌 Index Primaire (auto)                                        │
│     • id (PK)                                                    │
│                                                                  │
│  📌 Index Unique (existant)                                      │
│     • SERVER_ID (unique, db_index=True)                          │
│       → Une seule annotation par hostname                       │
│                                                                  │
│  📌 Indexes Simples (nouveaux)                                   │
│     • type                     ✨ NEW                            │
│       → Filtrage par type d'annotation                          │
│     • updated_at               ✨ NEW                            │
│       → Tri par date de dernière modification                   │
│                                                                  │
│  📌 Index Composé (nouveau)                                      │
│     • (SERVER_ID, type)        ✨ NEW                            │
│       → Recherche annotation + filtrage type                    │
│                                                                  │
│  💡 Total : ~5 indexes                                           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

-----

## 🚫 POURQUOI PAS DE FOREIGNKEY ?

### Problème avec ForeignKey dans ton workflow

```
❌ AVEC ForeignKey (ne marche PAS)
═══════════════════════════════════

Server                    ServerGroupSummary
  ├─► id (PK)               ├─► id (PK)
  └─► SERVER_ID             └─► server_id (FK → Server.id) ⚠️

Import :
1. DROP TABLE Server;
   💥 ERREUR : Cannot drop table referenced by foreign key

Solutions compliquées :
- SET FOREIGN_KEY_CHECKS = 0;  ← Dangereux
- DROP contrainte FK avant    ← Complexe
- Supprimer Summary d'abord   ← Perd les résumés


✅ SANS ForeignKey (ta solution)
═════════════════════════════════

Server                    ServerGroupSummary
  ├─► id (PK)               ├─► id (PK)
  └─► SERVER_ID             └─► SERVER_ID (CharField, pas FK) ✅

Import :
1. DROP TABLE Server;       ✅ Pas de contrainte
2. RENAME Staging → Server  ✅ Fonctionne
3. Summary reste intacte    ✅ Lien logique préservé

Avantages :
✅ Import simple et rapide
✅ Pas de gestion de contraintes
✅ Annotations persistent même si Server vide
✅ Plus flexible pour tes réimports complets
```

-----

## 📊 VOLUMÉTRIE EXEMPLE

```
┌───────────────────────────────────────────────────────────────┐
│                        VOLUMÉTRIE                             │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  Server                    : ~400 000 lignes                  │
│    ├─ Taille table         : ~500 MB                          │
│    └─ Taille indexes       : ~150 MB                          │
│                                                               │
│  ServerGroupSummary        : ~200 000 lignes                  │
│    ├─ Taille table         : ~80 MB                           │
│    └─ Taille indexes       : ~25 MB                           │
│                                                               │
│  ServerAnnotation          : ~5 000 lignes                    │
│    ├─ Taille table         : ~2 MB                            │
│    └─ Taille indexes       : ~500 KB                          │
│                                                               │
│  ImportStatus              : ~100 lignes                      │
│    ├─ Taille table         : ~50 KB                           │
│    └─ Taille indexes       : ~10 KB                           │
│                                                               │
│  TOTAL Base de données     : ~760 MB                          │
│                                                               │
│  Pendant import (tables doublées) : ~1.5 GB                   │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

-----

## 🎯 REQUÊTES TYPIQUES

### Requête 1 : Affichage page principale (mode groupé)

```sql
-- 1. Récupérer les hostnames paginés
SELECT DISTINCT SERVER_ID 
FROM Server 
WHERE PAMELA_ENVIRONMENT = 'PROD'
ORDER BY SERVER_ID
LIMIT 50 OFFSET 0;
                    ↓ Utilise index sur PAMELA_ENVIRONMENT ✅

-- 2. Récupérer les résumés pour ces hostnames
SELECT * 
FROM ServerGroupSummary 
WHERE SERVER_ID IN ('SRV001', 'SRV002', ...);
                    ↓ Utilise index sur SERVER_ID ✅

-- 3. Récupérer les annotations pour ces hostnames
SELECT * 
FROM ServerAnnotation 
WHERE SERVER_ID IN ('SRV001', 'SRV002', ...);
                    ↓ Utilise index sur SERVER_ID ✅
```

### Requête 2 : Filtrage multiple

```sql
-- Avec Q objects combinés (optimisé)
SELECT * 
FROM Server 
WHERE PAMELA_ENVIRONMENT = 'PROD'
  AND PAMELA_DATACENTER IN ('DC1', 'DC2')
  AND PAMELA_AREA = 'EUROPE'
ORDER BY SERVER_ID;
      ↓ Utilise les indexes sur chaque champ ✅
```

### Requête 3 : Génération des listbox

```sql
-- Liste distincte pour un filtre (avec cache 1h)
SELECT DISTINCT PAMELA_ENVIRONMENT 
FROM Server 
ORDER BY PAMELA_ENVIRONMENT;
                    ↓ Utilise index sur PAMELA_ENVIRONMENT ✅
```

-----

## 🎨 LÉGENDE DU SCHÉMA

```
Symboles utilisés :
═══════════════════

┌─┐  │  └─┘    Bordures de boîtes
├─┤  ─  ┼─┬    Séparateurs

◄───►            Relation bidirectionnelle (logique)
  │              Lien unidirectionnel
  ▼              Direction du flux
  →              Transformation

✅               Validé / OK / Actif
❌               Erreur / Problème / Interdit
⚠️               Attention / À risque
🔥               Critique / Important
✨               Nouveau / Ajouté
💡               Information / Conseil
📌               Point clé
🎯               Objectif / Cible

(PK)             Primary Key
(FK)             Foreign Key (pas utilisé ici)
(unique)         Contrainte d'unicité
managed=False    Table non gérée par Django
```

-----

## 📝 NOTES IMPORTANTES

1. **Pas de ForeignKey** :
- Lien logique via `SERVER_ID` (CharField)
- Permet le DROP/RENAME sans contraintes
- Plus flexible pour les réimports complets
1. **Tables Staging** :
- `managed = False` → Django ne touche pas
- Créées via `CREATE TABLE ... LIKE Server`
- Copient automatiquement les indexes
1. **Persistence des Annotations** :
- Survivent aux réimports (pas de CASCADE)
- Lien logique par `SERVER_ID`
- Historique JSON préservé
1. **Indexes automatiques** :
- Copiés via `LIKE` de Server vers Staging
- Préservés via `RENAME` de Staging vers Server
- Pas besoin de recréation manuelle
1. **Import atomique** :
- Validation avant swap
- DROP + RENAME en une transaction
- Rollback possible si problème

-----

## 🎉 CONCLUSION

Ton architecture est **vraiment bien pensée** pour ton use case :

✅ **Robuste** : Import atomique avec validation
✅ **Performant** : Indexes préservés automatiquement
✅ **Simple** : Pas de FK, pas de cascade complexe
✅ **Flexible** : Annotations persistent, réimports faciles
✅ **Sûr** : Staging permet validation avant swap

Le seul “inconvénient” (mineur) : Pas de contraintes référentielles au niveau DB, mais c’est un choix délibéré et intelligent pour ton workflow ! 👍
