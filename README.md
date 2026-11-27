# Vigie Freebox

**Application gratuite pour Windows et Mac qui enregistre les décrochages Wi-Fi et les coupures du lien TV de votre Freebox, et produit chaque semaine un rapport factuel à transmettre au support Free.**

> Application communautaire, open source (licence MIT), **non officielle et sans lien avec Free / Iliad**.
> Elle utilise uniquement l'API locale de la Freebox, en lecture seule, et ne transmet aucune donnée à l'extérieur.

## Ce que l'application surveille

Toutes les 20 secondes (réglable), l'application interroge votre Freebox et note :

| Domaine | Ce qui est enregistré |
|---|---|
| **Wi-Fi** | chaque appareil qui se déconnecte puis se reconnecte (durée d'absence), sur la Freebox Server ou sur le répéteur Free, avec la bande (2,4 / 5 / 6 GHz) et le signal ; les **coupures brèves** (l'appareil s'est réassocié entre deux relevés) ; les appareils encore listés mais dont la session radio est figée |
| **Décrochages collectifs** | au moins 3 appareils perdus au même instant sur la même borne : c'est la borne qui est en cause, pas les appareils |
| **Répéteur** | passage hors ligne et retour |
| **TV** | coupure et retour du lien Ethernet du Freebox Player, changement de vitesse négociée (1000 → 100 Mb/s), trames corrompues reçues sur le port du Player |
| **Box / Internet** | redémarrage de la Freebox Server, coupure Internet, perte du signal de la fibre |

### Les « sentinelles »

Dans l'onglet **Appareils Wi-Fi**, cochez comme sentinelles les appareils qui ne se mettent jamais en veille : caméras, prises connectées, imprimantes, etc. Un téléphone qui se déconnecte la nuit, c'est normal ; une caméra qui se déconnecte, non. Le rapport met ces appareils en avant.

## Les rapports

### Fréquence

Dans l'onglet **Rapports**, choisissez la fréquence, le ou les jours et l'heure :

| Fréquence | Quand | Période couverte |
|---|---|---|
| Quotidien | tous les jours | depuis la veille |
| Hebdomadaire | 1 fois par semaine, le jour choisi | 7 jours |
| Bihebdomadaire | 2 fois par semaine, les 2 jours choisis | depuis le rapport précédent |
| Bimensuel | le 1er et le 15 du mois | depuis le rapport précédent |

Si l'ordinateur était éteint à l'heure prévue, le rapport est fait au démarrage suivant. Le bouton **Générer maintenant** produit un rapport à la demande sur 24 heures, 7, 15 ou 30 jours.

### Contenu

Chaque rapport commence par un **message d'introduction**, modifiable dans l'onglet Rapports. Ce message est repris dans les e-mails et dans le courrier. Par défaut :

> Je paie un abonnement pour un service sans incident. Les incidents qui sont identifiés dans ce rapport relèvent de l'Article 10 (« Qualité de service ») de vos Conditions Générales d'Abonnement (CGA) et de l'obligation de résultat (Article 1231-1 du Code civil - Responsabilité contractuelle en cas d'inexécution ou de retard) imposée au professionnel.

Le rapport contient ensuite :
- les faits marquants rédigés ;
- les déconnexions par appareil, par borne et bande, par jour et par heure ;
- les incidents du lien TV ;
- le journal détaillé horodaté.

Il est enregistré dans `Documents/Vigie Freebox/` en trois formats : **PDF**, HTML et texte. Le bouton **Télécharger le PDF…** en enregistre une copie où vous voulez.

Les adresses MAC sont partiellement masquées par défaut. Vous pouvez aussi remplacer le nom des appareils par « Appareil 1, 2… ».

### Envoi par e-mail

Dans l'onglet **E-mail**, indiquez :
- la ou les adresses de destination ;
- votre messagerie : des réglages tout prêts existent pour Free, Gmail, Orange, SFR, Laposte.net, Yahoo et iCloud ;
- votre identifiant et votre mot de passe. Pour Gmail, Yahoo et iCloud, utilisez un *mot de passe d'application*.

Le mot de passe est rangé dans le trousseau sécurisé du système (Gestionnaire d'identification Windows, Trousseau macOS).

Cochez **Envoyer automatiquement chaque rapport programmé** pour recevoir chaque rapport en PDF. Le bouton **Envoyer par e-mail** envoie le rapport sélectionné.

### Transmettre à Free

Free ne propose pas d'adresse e-mail pour son service client : les réclamations écrites passent par courrier ou par l'Espace Abonné. L'onglet **Réclamation Free** propose trois actions :

- **Préparer le courrier recommandé (PDF)** : une lettre de réclamation à vos nom et coordonnées, adressée à Free – Service Réclamation (ou Service National Consommateur) – 75371 Paris Cedex 08. Elle reprend le message d'introduction et les faits marquants, et contient le rapport complet en annexe. Il ne reste qu'à l'envoyer en recommandé avec accusé de réception, sur papier ou par la lettre recommandée en ligne de La Poste.
- **Préparer l'envoi dans la messagerie Free** (messagerie « Mon Assistance » de l'Espace Abonné). L'application :
  - génère le PDF du rapport ;
  - copie le texte de la réclamation dans le presse-papiers ;
  - ouvre la messagerie Free dans le navigateur, à l'adresse `https://monassistance.free.fr/messagerie?id=<n° de l'identifiant Freebox>` ;
  - ouvre le dossier du PDF.

  L'abonné se connecte (identifiant Freebox et mot de passe). Il clique sur *Répondre*, colle le texte, joint le PDF avec *Importer un document* et valide. Le mot de passe Free n'est jamais demandé ni stocké par l'application.
- Un lien vers le **Médiateur des communications électroniques**, dernière étape amiable.

Les étapes de réclamation :
1. Service Réclamation.
2. Sans réponse satisfaisante sous un mois : Service National Consommateur.
3. Sans réponse satisfaisante sous un mois : Médiateur, gratuit, à saisir dans l'année qui suit la première réclamation écrite.

> L'application fournit des faits et des modèles de courrier ; elle ne constitue pas un conseil juridique.

## Installation

1. Téléchargez la dernière version dans l'onglet **[Releases](../../releases)** de cette page :
   - Windows : `VigieFreebox-Windows.zip`
   - Mac récent (puce Apple M1, M2…) : `VigieFreebox-macOS-AppleSilicon.zip`
   - Mac Intel : `VigieFreebox-macOS-Intel.zip`
2. Décompressez le fichier.
3. **Première ouverture.** L'application n'est pas signée par un éditeur payant, donc le système demande une confirmation :
   - **Windows** : si « Windows a protégé votre ordinateur » s'affiche, cliquez sur *Informations complémentaires* puis *Exécuter quand même*.
   - **Mac** : faites un clic droit sur *Vigie Freebox*, choisissez *Ouvrir*, puis confirmez *Ouvrir*. Sur macOS 15 et suivants, si l'ouverture est bloquée, allez dans *Réglages Système › Confidentialité et sécurité* et cliquez sur *Ouvrir quand même*. Acceptez ensuite l'accès au **réseau local** : il est indispensable pour joindre la Freebox.

## Premier lancement : autoriser l'application sur la Freebox

1. L'ordinateur doit être connecté au réseau de la Freebox, en Wi-Fi ou par câble.
2. Cliquez sur **Autoriser**.
3. Validez la demande sur l'écran de la Freebox Server (flèche ►, puis OK). Vous avez environ une minute.
4. Si l'application signale des **droits insuffisants** :
   - ouvrez Freebox OS (http://mafreebox.freebox.fr) › *Paramètres de la Freebox* › *Gestion des accès* › onglet *Applications* › **Vigie Freebox** ;
   - cochez **Modification des réglages de la Freebox** : la Freebox exige ce droit pour *lire* l'état du Wi-Fi et des ports ; l'application ne modifie aucun réglage ;
   - cochez aussi l'accès à **l'explorateur réseau**.

## À savoir

- **La surveillance ne fonctionne que quand l'application est ouverte.** Cochez *Lancer automatiquement à l'ouverture de session* dans les Paramètres. Fermer la fenêtre propose de la réduire plutôt que de quitter.
- L'ordinateur doit rester allumé. Une veille prolongée interrompt les relevés. Le rapport indique la **couverture** (le pourcentage du temps réellement surveillé) pour rester honnête sur les chiffres.
- Les données (configuration, journal, mesures) sont conservées 90 jours dans :
  - `%APPDATA%\VigieFreebox` sous Windows ;
  - `~/Library/Application Support/VigieFreebox` sous Mac.
- Si le Player n'est pas détecté automatiquement, choisissez son port Ethernet dans les Paramètres.

## Pour les développeurs

```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q          # tests avec une fausse Freebox
python main.py               # lancer l'application (Python 3.10+ avec Tk)
```

### Publier une nouvelle version

Les fichiers Windows et Mac sont construits automatiquement par GitHub Actions (`.github/workflows/build.yml`) :

```bash
git tag v1.0.0
git push origin v1.0.0
```

Quelques minutes plus tard, la page *Releases* propose les trois fichiers à télécharger.

L'API utilisée est documentée sur https://dev.freebox.fr/sdk/os/ (points d'accès suivants, tous en lecture) :
- `/lan/browser/pub/`
- `/repeater/`
- `/wifi/ap/`
- `/switch/status/`, `/switch/port/{id}/stats/`
- `/connection/`, `/connection/ftth/`
- `/system/`
