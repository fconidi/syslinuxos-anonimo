"""Session language detection and UI translations. GPL-3.0-or-later.

English is the source and fallback language. LANGUAGE preferences apply
unless the message locale is C/POSIX. The helper and the watcher write
English; translation happens in the user's process.
"""

import os

SUPPORTED = ('en', 'it', 'fr', 'de', 'es')


def _base(locale):
    return locale.strip().split('.')[0].split('@')[0].replace('-', '_').split('_')[0].lower()


def detect_language(environ=None):
    env = os.environ if environ is None else environ
    locale = env.get('LC_ALL') or env.get('LC_MESSAGES') or env.get('LANG') or 'C'
    if _base(locale) in ('c', 'posix'):
        return 'en'
    preferences = env.get('LANGUAGE') or locale
    for preference in preferences.split(':'):
        language = _base(preference)
        if language in SUPPORTED:
            return language
    return 'en'


# English source: Italian, French, German, Spanish.
TRANSLATIONS = {
    'Off': ('Spento', 'Désactivé', 'Aus', 'Apagado'),
    'Connecting': ('Connessione in corso', 'Connexion en cours', 'Verbindung wird aufgebaut', 'Conectando'),
    'Protected': ('Protetto', 'Protégé', 'Geschützt', 'Protegido'),
    'Error': ('Errore', 'Erreur', 'Fehler', 'Error'),
    'Settings must be a JSON object': ('Le impostazioni devono essere un oggetto JSON', 'Les paramètres doivent être un objet JSON', 'Die Einstellungen müssen ein JSON-Objekt sein', 'La configuración debe ser un objeto JSON'),
    'Unknown setting': ('Impostazione sconosciuta', 'Paramètre inconnu', 'Unbekannte Einstellung', 'Ajuste desconocido'),
    'Invalid setting value': ('Valore di impostazione non valido', 'Valeur de paramètre non valide', 'Ungültiger Einstellungswert', 'Valor de ajuste no válido'),
    'Cannot read settings': ('Impossibile leggere le impostazioni', 'Impossible de lire les paramètres', 'Einstellungen können nicht gelesen werden', 'No se puede leer la configuración'),
    'Invalid obfs4 bridge line': ('Riga bridge obfs4 non valida', 'Ligne de pont obfs4 non valide', 'Ungültige obfs4-Bridge-Zeile', 'Línea de puente obfs4 no válida'),
    'Too many bridge lines': ('Troppe righe bridge', 'Trop de lignes de pont', 'Zu viele Bridge-Zeilen', 'Demasiadas líneas de puente'),
    'Bridge list too long': ('Elenco dei bridge troppo lungo', 'Liste de ponts trop longue', 'Bridge-Liste zu lang', 'Lista de puentes demasiado larga'),
    'Unknown bridge type': ('Tipo di bridge sconosciuto', 'Type de pont inconnu', 'Unbekannter Bridge-Typ', 'Tipo de puente desconocido'),
    'The obfs4 bridge program is not installed': ('Il programma dei bridge obfs4 non è installato', 'Le programme des ponts obfs4 n’est pas installé', 'Das obfs4-Bridge-Programm ist nicht installiert', 'El programa de puentes obfs4 no está instalado'),
    'The snowflake bridge program is not installed': ('Il programma dei bridge snowflake non è installato', 'Le programme des ponts snowflake n’est pas installé', 'Das snowflake-Bridge-Programm ist nicht installiert', 'El programa de puentes snowflake no está instalado'),
    'No obfs4 bridge lines available': ('Nessuna riga bridge obfs4 disponibile', 'Aucune ligne de pont obfs4 disponible', 'Keine obfs4-Bridge-Zeilen verfügbar', 'No hay líneas de puente obfs4'),
    'No snowflake bridge lines available': ('Nessuna riga bridge snowflake disponibile', 'Aucune ligne de pont snowflake disponible', 'Keine snowflake-Bridge-Zeilen verfügbar', 'No hay líneas de puente snowflake'),
    'Invalid command': ('Comando non valido', 'Commande non valide', 'Ungültiger Befehl', 'Comando no válido'),
    'The helper must run as root': ('L’helper deve essere eseguito come root', 'L’assistant doit s’exécuter en root', 'Das Hilfsprogramm muss als root laufen', 'El programa auxiliar debe ejecutarse como root'),
    'anonimo is busy: try again in a moment': ('anonimo è occupato: riprova tra poco', 'anonimo est occupé : réessayez dans un instant', 'anonimo ist beschäftigt: gleich noch einmal versuchen', 'anonimo está ocupado: inténtalo de nuevo en un momento'),
    'Tor did not connect in time': ('Tor non si è connesso in tempo', 'Tor ne s’est pas connecté à temps', 'Tor hat sich nicht rechtzeitig verbunden', 'Tor no se conectó a tiempo'),
    'Tor stopped with an error': ('Tor si è fermato con un errore', 'Tor s’est arrêté avec une erreur', 'Tor wurde mit einem Fehler beendet', 'Tor se detuvo con un error'),
    'Cannot start Tor': ('Impossibile avviare Tor', 'Impossible de démarrer Tor', 'Tor kann nicht gestartet werden', 'No se puede iniciar Tor'),
    'Tor is not running': ('Tor non è in esecuzione', 'Tor n’est pas en cours d’exécution', 'Tor läuft nicht', 'Tor no se está ejecutando'),
    'Tor did not stop cleanly': ('Tor non si è fermato correttamente', 'Tor ne s’est pas arrêté proprement', 'Tor wurde nicht sauber beendet', 'Tor no se detuvo correctamente'),
    'Add at least one obfs4 bridge line first': ('Aggiungi prima almeno una riga bridge obfs4', 'Ajoutez d’abord au moins une ligne de pont obfs4', 'Zuerst mindestens eine obfs4-Bridge-Zeile hinzufügen', 'Añade primero al menos una línea de puente obfs4'),
    'Invalid settings input': ('Dati delle impostazioni non validi', 'Données de paramètres non valides', 'Ungültige Einstellungsdaten', 'Datos de configuración no válidos'),
    'Input too large': ('Dati troppo grandi', 'Données trop volumineuses', 'Eingabe zu groß', 'Datos demasiado grandes'),
    'System user _anonimo is missing': ('Manca l’utente di sistema _anonimo', 'L’utilisateur système _anonimo est absent', 'Der Systembenutzer _anonimo fehlt', 'Falta el usuario del sistema _anonimo'),
    '{state} · {progress}%': ('{state} · {progress}%', '{state} · {progress} %', '{state} · {progress} %', '{state} · {progress}%'),
    '{state}: {detail}': ('{state}: {detail}', '{state} : {detail}', '{state}: {detail}', '{state}: {detail}'),
    'Check that the date and time of this computer are correct.': ('Verifica che data e ora del computer siano corrette.', 'Vérifiez que la date et l’heure de l’ordinateur sont correctes.', 'Prüfen, ob Datum und Uhrzeit des Computers stimmen.', 'Comprueba que la fecha y la hora del equipo son correctas.'),
    'Switch anonimo off to restore the normal network.': ('Spegni anonimo per ripristinare la rete normale.', 'Désactivez anonimo pour rétablir le réseau normal.', 'anonimo ausschalten, um das normale Netzwerk wiederherzustellen.', 'Apaga anonimo para restablecer la red normal.'),
    'Run "anonimo stop" to restore the normal network.': ('Esegui "anonimo stop" per ripristinare la rete normale.', 'Lancez "anonimo stop" pour rétablir le réseau normal.', '"anonimo stop" ausführen, um das normale Netzwerk wiederherzustellen.', 'Ejecuta "anonimo stop" para restablecer la red normal.'),
    'Connecting to Tor… {progress}%': ('Connessione a Tor… {progress}%', 'Connexion à Tor… {progress} %', 'Verbindung zu Tor… {progress} %', 'Conectando con Tor… {progress}%'),
    'Error: {message}': ('Errore: {message}', 'Erreur : {message}', 'Fehler: {message}', 'Error: {message}'),
    'anonimo was switched off.': ('anonimo è stato spento.', 'anonimo a été désactivé.', 'anonimo wurde ausgeschaltet.', 'anonimo se ha apagado.'),
    'Protected: traffic goes through Tor.': ('Protetto: il traffico passa da Tor.', 'Protégé : le trafic passe par Tor.', 'Geschützt: Der Datenverkehr läuft über Tor.', 'Protegido: el tráfico pasa por Tor.'),
    'Off: normal network restored.': ('Spento: rete normale ripristinata.', 'Désactivé : réseau normal rétabli.', 'Aus: normales Netzwerk wiederhergestellt.', 'Apagado: red normal restablecida.'),
    'Connecting to Tor…': ('Connessione a Tor…', 'Connexion à Tor…', 'Verbindung zu Tor…', 'Conectando con Tor…'),
    'New identity requested.': ('Nuova identità richiesta.', 'Nouvelle identité demandée.', 'Neue Identität angefordert.', 'Nueva identidad solicitada.'),
    'Settings saved.': ('Impostazioni salvate.', 'Paramètres enregistrés.', 'Einstellungen gespeichert.', 'Configuración guardada.'),
    'Bridges saved: {count}': ('Bridge salvati: {count}', 'Ponts enregistrés : {count}', 'Bridges gespeichert: {count}', 'Puentes guardados: {count}'),
    'Tor check failed: {message}': ('Verifica Tor non riuscita: {message}', 'Échec de la vérification Tor : {message}', 'Tor-Prüfung fehlgeschlagen: {message}', 'La comprobación de Tor falló: {message}'),
    'Traffic goes through Tor. Exit address: {ip}': ('Il traffico passa da Tor. Indirizzo di uscita: {ip}', 'Le trafic passe par Tor. Adresse de sortie : {ip}', 'Der Datenverkehr läuft über Tor. Ausgangsadresse: {ip}', 'El tráfico pasa por Tor. Dirección de salida: {ip}'),
    'Warning: traffic does NOT go through Tor. Address: {ip}': ('Attenzione: il traffico NON passa da Tor. Indirizzo: {ip}', 'Attention : le trafic NE passe PAS par Tor. Adresse : {ip}', 'Achtung: Der Datenverkehr läuft NICHT über Tor. Adresse: {ip}', 'Atención: el tráfico NO pasa por Tor. Dirección: {ip}'),
    'Traffic does not go through Tor': ('Il traffico non passa da Tor', 'Le trafic ne passe pas par Tor', 'Der Datenverkehr läuft nicht über Tor', 'El tráfico no pasa por Tor'),
    'Cannot reach check.torproject.org': ('Impossibile raggiungere check.torproject.org', 'Impossible de joindre check.torproject.org', 'check.torproject.org ist nicht erreichbar', 'No se puede contactar con check.torproject.org'),
    'Unexpected answer from check.torproject.org': ('Risposta inattesa da check.torproject.org', 'Réponse inattendue de check.torproject.org', 'Unerwartete Antwort von check.torproject.org', 'Respuesta inesperada de check.torproject.org'),
    'Authorization cancelled or failed.': ('Autorizzazione annullata o non riuscita.', 'Autorisation annulée ou refusée.', 'Berechtigung abgebrochen oder fehlgeschlagen.', 'Autorización cancelada o fallida.'),
    'Install the syslinuxos-anonimo package to use this command.': ('Installa il pacchetto syslinuxos-anonimo per usare questo comando.', 'Installez le paquet syslinuxos-anonimo pour utiliser cette commande.', 'Für diesen Befehl das Paket syslinuxos-anonimo installieren.', 'Instala el paquete syslinuxos-anonimo para usar este comando.'),
    'Route all traffic of this computer through Tor.': ('Instrada tutto il traffico del computer attraverso Tor.', 'Fait passer tout le trafic de l’ordinateur par Tor.', 'Leitet den gesamten Datenverkehr des Computers über Tor.', 'Envía todo el tráfico del equipo a través de Tor.'),
    'Switch anonimo on': ('Accendi anonimo', 'Activer anonimo', 'anonimo einschalten', 'Encender anonimo'),
    'Switch anonimo off': ('Spegni anonimo', 'Désactiver anonimo', 'anonimo ausschalten', 'Apagar anonimo'),
    'Close network applications first': ('Chiudi prima le applicazioni di rete', 'Fermer d’abord les applications réseau', 'Zuerst Netzwerkanwendungen schließen', 'Cerrar primero las aplicaciones de red'),
    'Do not close applications': ('Non chiudere le applicazioni', 'Ne pas fermer les applications', 'Anwendungen nicht schließen', 'No cerrar las aplicaciones'),
    'Show the current state': ('Mostra lo stato attuale', 'Afficher l’état actuel', 'Aktuellen Zustand anzeigen', 'Mostrar el estado actual'),
    'Machine-readable output': ('Output leggibile da programmi', 'Sortie lisible par une machine', 'Maschinenlesbare Ausgabe', 'Salida legible por máquina'),
    'Ask check.torproject.org whether traffic uses Tor': ('Chiedi a check.torproject.org se il traffico usa Tor', 'Demander à check.torproject.org si le trafic passe par Tor', 'check.torproject.org fragen, ob der Verkehr Tor nutzt', 'Preguntar a check.torproject.org si el tráfico usa Tor'),
    'Use new Tor circuits for new connections': ('Usa nuovi circuiti Tor per le nuove connessioni', 'Utiliser de nouveaux circuits Tor pour les nouvelles connexions', 'Neue Tor-Verbindungswege für neue Verbindungen nutzen', 'Usar nuevos circuitos de Tor para las nuevas conexiones'),
    'Show or change the settings': ('Mostra o modifica le impostazioni', 'Afficher ou modifier les paramètres', 'Einstellungen anzeigen oder ändern', 'Mostrar o cambiar la configuración'),
    'Reach the local network directly': ('Raggiungi direttamente la rete locale', 'Accéder directement au réseau local', 'Lokales Netzwerk direkt erreichen', 'Acceder directamente a la red local'),
    'Bridge type': ('Tipo di bridge', 'Type de pont', 'Bridge-Typ', 'Tipo de puente'),
    'Switch on automatically at boot': ('Accendi automaticamente all’avvio', 'Activer automatiquement au démarrage', 'Beim Systemstart automatisch einschalten', 'Encender automáticamente al arrancar'),
    'Close network applications on start and stop': ('Chiudi le applicazioni di rete all’accensione e allo spegnimento', 'Fermer les applications réseau à l’activation et à la désactivation', 'Netzwerkanwendungen beim Ein- und Ausschalten schließen', 'Cerrar las aplicaciones de red al encender y al apagar'),
    'Show or set the obfs4 bridge lines': ('Mostra o imposta le righe bridge obfs4', 'Afficher ou définir les lignes de pont obfs4', 'obfs4-Bridge-Zeilen anzeigen oder festlegen', 'Mostrar o definir las líneas de puente obfs4'),
    'File with one bridge line per line, or - for standard input': ('File con una riga bridge per riga, oppure - per lo standard input', 'Fichier avec une ligne de pont par ligne, ou - pour l’entrée standard', 'Datei mit einer Bridge-Zeile pro Zeile oder - für die Standardeingabe', 'Archivo con una línea de puente por línea, o - para la entrada estándar'),
    'Close these applications first? {names} [y/N]': ('Chiudere prima queste applicazioni? {names} [s/N]', 'Fermer d’abord ces applications ? {names} [o/N]', 'Diese Anwendungen zuerst schließen? {names} [j/N]', '¿Cerrar primero estas aplicaciones? {names} [s/N]'),
    'y': ('s', 'o', 'j', 's'),
    'Cannot read the bridge file: {path}': ('Impossibile leggere il file dei bridge: {path}', 'Impossible de lire le fichier des ponts : {path}', 'Bridge-Datei kann nicht gelesen werden: {path}', 'No se puede leer el archivo de puentes: {path}'),
    'New identity': ('Nuova identità', 'Nouvelle identité', 'Neue Identität', 'Nueva identidad'),
    'Check Tor': ('Verifica Tor', 'Vérifier Tor', 'Tor prüfen', 'Comprobar Tor'),
    'Settings': ('Impostazioni', 'Paramètres', 'Einstellungen', 'Configuración'),
    'Reach the local network directly (printers, NAS)': ('Raggiungi direttamente la rete locale (stampanti, NAS)', 'Accéder directement au réseau local (imprimantes, NAS)', 'Lokales Netzwerk direkt erreichen (Drucker, NAS)', 'Acceder directamente a la red local (impresoras, NAS)'),
    'Close network applications and clean caches on start and stop': ('Chiudi le applicazioni di rete e pulisci le cache all’accensione e allo spegnimento', 'Fermer les applications réseau et vider les caches à l’activation et à la désactivation', 'Netzwerkanwendungen schließen und Caches leeren beim Ein- und Ausschalten', 'Cerrar las aplicaciones de red y limpiar las cachés al encender y al apagar'),
    'Show the icon at login': ('Mostra l’icona all’accesso', 'Afficher l’icône à la connexion', 'Symbol bei der Anmeldung anzeigen', 'Mostrar el icono al iniciar sesión'),
    'Bridges:': ('Bridge:', 'Ponts :', 'Bridges:', 'Puentes:'),
    'None': ('Nessuno', 'Aucun', 'Keine', 'Ninguno'),
    'The bridge program is not installed': ('Il programma dei bridge non è installato', 'Le programme des ponts n’est pas installé', 'Das Bridge-Programm ist nicht installiert', 'El programa de puentes no está instalado'),
    'Edit obfs4 bridges…': ('Modifica bridge obfs4…', 'Modifier les ponts obfs4…', 'obfs4-Bridges bearbeiten…', 'Editar puentes obfs4…'),
    'About': ('Informazioni', 'À propos', 'Über', 'Acerca de'),
    'Switch on': ('Accendi', 'Activer', 'Einschalten', 'Encender'),
    'Switch off': ('Spegni', 'Désactiver', 'Ausschalten', 'Apagar'),
    'These applications will be closed: {names}': ('Queste applicazioni verranno chiuse: {names}', 'Ces applications seront fermées : {names}', 'Diese Anwendungen werden geschlossen: {names}', 'Se cerrarán estas aplicaciones: {names}'),
    'Close and continue': ('Chiudi e continua', 'Fermer et continuer', 'Schließen und fortfahren', 'Cerrar y continuar'),
    'Continue without closing': ('Continua senza chiudere', 'Continuer sans fermer', 'Ohne Schließen fortfahren', 'Continuar sin cerrar'),
    'Checking…': ('Verifica in corso…', 'Vérification…', 'Wird geprüft…', 'Comprobando…'),
    'obfs4 bridges': ('Bridge obfs4', 'Ponts obfs4', 'obfs4-Bridges', 'Puentes obfs4'),
    'Paste the bridge lines from https://bridges.torproject.org, one per line. Saving replaces the current list.': ('Incolla le righe bridge da https://bridges.torproject.org, una per riga. Il salvataggio sostituisce l’elenco attuale.', 'Collez les lignes de pont de https://bridges.torproject.org, une par ligne. L’enregistrement remplace la liste actuelle.', 'Bridge-Zeilen von https://bridges.torproject.org einfügen, eine pro Zeile. Speichern ersetzt die aktuelle Liste.', 'Pega las líneas de puente de https://bridges.torproject.org, una por línea. Al guardar se sustituye la lista actual.'),
    'Inspired by AnonSurf by the Parrot Security team. No AnonSurf code is used.': ('Ispirato ad AnonSurf del team Parrot Security. Non usa codice di AnonSurf.', 'Inspiré d’AnonSurf de l’équipe Parrot Security. Aucun code d’AnonSurf n’est utilisé.', 'Inspiriert von AnonSurf des Parrot-Security-Teams. Es wird kein AnonSurf-Code verwendet.', 'Inspirado en AnonSurf del equipo Parrot Security. No usa código de AnonSurf.'),
    'Tor is a trademark of The Tor Project, Inc.': ('Tor è un marchio di The Tor Project, Inc.', 'Tor est une marque de The Tor Project, Inc.', 'Tor ist eine Marke von The Tor Project, Inc.', 'Tor es una marca de The Tor Project, Inc.'),
    'Open window': ('Apri finestra', 'Ouvrir la fenêtre', 'Fenster öffnen', 'Abrir ventana'),
    'Quit': ('Esci', 'Quitter', 'Beenden', 'Salir'),
}

# Fixed English messages written by the helper; translated for display only.
HELPER_MESSAGES = (
    'Settings must be a JSON object', 'Unknown setting', 'Invalid setting value',
    'Cannot read settings', 'Invalid obfs4 bridge line', 'Too many bridge lines',
    'Bridge list too long', 'Unknown bridge type', 'The obfs4 bridge program is not installed',
    'The snowflake bridge program is not installed', 'No obfs4 bridge lines available',
    'No snowflake bridge lines available', 'Invalid command', 'The helper must run as root',
    'anonimo is busy: try again in a moment', 'Tor did not connect in time',
    'Tor stopped with an error', 'Cannot start Tor', 'Tor is not running',
    'Tor did not stop cleanly', 'Add at least one obfs4 bridge line first',
    'Invalid settings input', 'Input too large', 'System user _anonimo is missing',
    'Cannot reach check.torproject.org', 'Unexpected answer from check.torproject.org',
)


def _lookup(text):
    language = detect_language()
    translations = TRANSLATIONS.get(text)
    if language != 'en' and translations:
        return translations[SUPPORTED.index(language) - 1]
    return text


def tr(text, /, **values):
    # Positional-only, so placeholders may be called {message} or {text}.
    text = _lookup(text)
    return text.format(**values) if values else text


def helper_message(text):
    """Translate a fixed helper message; anything else is shown as it is."""
    return _lookup(text)
