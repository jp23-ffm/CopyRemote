#Requires -Modules Microsoft.Graph.Mail, Microsoft.Graph.Users

<#
.SYNOPSIS
    Biblioth�que de wrappers pour migrer EWS vers Microsoft Graph
    
.DESCRIPTION
    Ces fonctions imitent le comportement des objets EWS pour minimiser
    les changements dans les scripts existants lors de la migration vers Graph.
    
.NOTES
    Pr�requis: Connect-MgGraph doit �tre appel� avant d'utiliser ces fonctions
    Permissions n�cessaires: Mail.ReadWrite, Mail.ReadWrite.Shared (si d�l�gation)
#>

# Variable globale pour stocker l'utilisateur en cours (pour impersonation)
$script:EwsCompat_CurrentUser = $null

#region Configuration et Connexion

<#
.SYNOPSIS
    Initialise la connexion Graph en mode "impersonation"
    
.DESCRIPTION
    Remplace la cr�ation du ExchangeService EWS avec impersonation.
    Configure l'utilisateur cible pour toutes les op�rations suivantes.
    
.PARAMETER UserEmail
    Adresse email de la bo�te aux lettres � consulter
    
.EXAMPLE
    Initialize-EwsCompatConnection -UserEmail "user@domain.com"
#>
function Initialize-EwsCompatConnection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$UserEmail
    )
    
    try {
        # V�rifier que Graph est connect�
        $context = Get-MgContext
        if (-not $context) {
            throw "Microsoft Graph n'est pas connect�. Utilisez Connect-MgGraph d'abord."
        }
        
        # Stocker l'utilisateur pour les op�rations futures
        $script:EwsCompat_CurrentUser = $UserEmail
        
        Write-Verbose "Connexion Graph initialis�e pour: $UserEmail"
        
        return [PSCustomObject]@{
            Success = $true
            User = $UserEmail
            Context = $context
        }
    }
    catch {
        Write-Error "Erreur lors de l'initialisation: $_"
        return [PSCustomObject]@{
            Success = $false
            Error = $_.Exception.Message
        }
    }
}

#endregion

#region Gestion des Dossiers

<#
.SYNOPSIS
    R�cup�re un dossier par son nom (�quivalent FindFolders)
    
.DESCRIPTION
    Simule ExchangeService.FindFolders() en recherchant un dossier par nom
    
.PARAMETER ParentFolderId
    ID du dossier parent (ou "Inbox" pour la bo�te de r�ception)
    
.PARAMETER DisplayName
    Nom du dossier � rechercher
    
.EXAMPLE
    $folder = Get-EwsCompatFolder -ParentFolderId "Inbox" -DisplayName "TODO"
#>
function Get-EwsCompatFolder {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ParentFolderId,
        
        [Parameter(Mandatory = $false)]
        [string]$DisplayName
    )
    
    if (-not $script:EwsCompat_CurrentUser) {
        throw "Utilisateur non initialis�. Appelez Initialize-EwsCompatConnection d'abord."
    }
    
    try {
        # G�rer le cas sp�cial "Inbox" - on doit d'abord r�cup�rer le dossier Inbox pour avoir son ID
        if ($ParentFolderId -eq "Inbox") {
            Write-Verbose "R�cup�ration du dossier Inbox"
            $inboxFolder = Get-MgUserMailFolder -UserId $script:EwsCompat_CurrentUser -MailFolderId "Inbox"
            $ParentFolderId = $inboxFolder.Id
        }
        
        # R�cup�rer les sous-dossiers
        $folders = Get-MgUserMailFolderChildFolder -UserId $script:EwsCompat_CurrentUser -MailFolderId $ParentFolderId
        
        # Filtrer par nom si sp�cifi�
        if ($DisplayName) {
            $folders = $folders | Where-Object { $_.DisplayName -eq $DisplayName }
        }
        
        # Convertir en objets compatibles EWS
        $compatFolders = @()
        foreach ($folder in $folders) {
            $compatFolders += New-EwsCompatFolder -GraphFolder $folder
        }
        
        return $compatFolders
    }
    catch {
        Write-Error "Erreur lors de la r�cup�ration des dossiers: $_"
        Write-Verbose "D�tails: $($_.Exception.Message)"
        return $null
    }
}

<#
.SYNOPSIS
    Cr�e un objet dossier compatible EWS
    
.DESCRIPTION
    Fonction interne pour convertir un dossier Graph en objet compatible EWS
#>
function New-EwsCompatFolder {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $GraphFolder
    )
    
    $obj = [PSCustomObject]@{
        Id = $GraphFolder.Id
        DisplayName = $GraphFolder.DisplayName
        TotalCount = $GraphFolder.TotalItemCount
        UnreadCount = $GraphFolder.UnreadItemCount
        ChildFolderCount = $GraphFolder.ChildFolderCount
    }
    
    # Ajouter un type pour faciliter l'identification
    $obj.PSObject.TypeNames.Insert(0, 'EwsCompat.Folder')
    
    return $obj
}

#endregion

#region Gestion des Messages

<#
.SYNOPSIS
    R�cup�re les messages d'un dossier (�quivalent FindItems)
    
.DESCRIPTION
    Simule FolderObject.FindItems() avec support du tri et de la pagination
    
.PARAMETER FolderId
    ID du dossier ou objet dossier compatible EWS
    
.PARAMETER Top
    Nombre de messages � r�cup�rer (d�faut: 1)
    
.PARAMETER OrderBy
    Champ de tri: "DateTimeReceived" ou "Subject"
    
.PARAMETER Ascending
    Ordre croissant (true) ou d�croissant (false)
    
.EXAMPLE
    $messages = Get-EwsCompatMessages -FolderId $folder.Id -Top 1 -OrderBy "DateTimeReceived" -Ascending $true
#>
function Get-EwsCompatMessages {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $FolderId,
        
        [Parameter(Mandatory = $false)]
        [int]$Top = 1,
        
        [Parameter(Mandatory = $false)]
        [ValidateSet("DateTimeReceived", "Subject", "From")]
        [string]$OrderBy = "DateTimeReceived",
        
        [Parameter(Mandatory = $false)]
        [bool]$Ascending = $true
    )
    
    if (-not $script:EwsCompat_CurrentUser) {
        throw "Utilisateur non initialis�. Appelez Initialize-EwsCompatConnection d'abord."
    }
    
    try {
        # Extraire l'ID si c'est un objet
        if ($FolderId -is [PSCustomObject] -and $FolderId.Id) {
            $FolderId = $FolderId.Id
        }
        
        # R�cup�rer les messages
        $messages = Get-MgUserMailFolderMessage -UserId $script:EwsCompat_CurrentUser -MailFolderId $FolderId -Top $Top -All:$false
        
        # Trier les messages (Graph ne supporte pas toujours l'orderby via API)
        switch ($OrderBy) {
            "DateTimeReceived" {
                if ($Ascending) {
                    $messages = $messages | Sort-Object ReceivedDateTime
                } else {
                    $messages = $messages | Sort-Object ReceivedDateTime -Descending
                }
            }
            "Subject" {
                if ($Ascending) {
                    $messages = $messages | Sort-Object Subject
                } else {
                    $messages = $messages | Sort-Object Subject -Descending
                }
            }
        }
        
        # Prendre seulement le Top demand� apr�s tri
        $messages = $messages | Select-Object -First $Top
        
        # Convertir en objets compatibles EWS
        $compatMessages = @()
        foreach ($message in $messages) {
            # R�cup�rer les pi�ces jointes pour ce message
            $attachments = Get-MgUserMessageAttachment -UserId $script:EwsCompat_CurrentUser -MessageId $message.Id -ErrorAction SilentlyContinue
            
            $compatMessages += New-EwsCompatMessage -GraphMessage $message -GraphAttachments $attachments
        }
        
        # Cr�er un objet collection compatible avec .Load()
        $collection = [PSCustomObject]@{
            Items = $compatMessages
            Count = $compatMessages.Count
        }
        
        # Ajouter une m�thode Load() factice (pour compatibilit�)
        $collection | Add-Member -MemberType ScriptMethod -Name "Load" -Value {
            # D�j� charg�, ne fait rien
            Write-Verbose "Load() appel� - donn�es d�j� charg�es avec Graph"
        }
        
        return $collection
    }
    catch {
        Write-Error "Erreur lors de la r�cup�ration des messages: $_"
        return $null
    }
}

<#
.SYNOPSIS
    Cr�e un objet message compatible EWS
    
.DESCRIPTION
    Fonction interne pour convertir un message Graph en objet compatible EWS
#>
function New-EwsCompatMessage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $GraphMessage,
        
        [Parameter(Mandatory = $false)]
        $GraphAttachments
    )
    
    # Convertir les pi�ces jointes
    $compatAttachments = @()
    if ($GraphAttachments) {
        foreach ($att in $GraphAttachments) {
            $compatAttachments += New-EwsCompatAttachment -GraphAttachment $att -MessageId $GraphMessage.Id
        }
    }
    
    # Cr�er l'objet principal
    $obj = [PSCustomObject]@{
        Id = $GraphMessage.Id
        Subject = $GraphMessage.Subject
        DateTimeReceived = $GraphMessage.ReceivedDateTime
        IsRead = $GraphMessage.IsRead
        HasAttachments = $GraphMessage.HasAttachments
        Body = $GraphMessage.Body.Content
        BodyType = $GraphMessage.Body.ContentType
        Attachments = $compatAttachments
        
        # Propri�t� From compatible EWS
        From = [PSCustomObject]@{
            Address = $GraphMessage.From.EmailAddress.Address
            Name = $GraphMessage.From.EmailAddress.Name
        }
        
        # Pour compatibilit� avec .items.Move()
        Items = [PSCustomObject]@{
            _graphId = $GraphMessage.Id
            _graphUser = $script:EwsCompat_CurrentUser
        }
    }
    
    # Ajouter la m�thode Move
    $obj.Items | Add-Member -MemberType ScriptMethod -Name "Move" -Value {
        param($DestinationFolderId)
        
        # Extraire l'ID si c'est un objet
        if ($DestinationFolderId -is [PSCustomObject] -and $DestinationFolderId.Id) {
            $DestinationFolderId = $DestinationFolderId.Id
        }
        
        try {
            Move-MgUserMessage -UserId $this._graphUser -MessageId $this._graphId -DestinationId $DestinationFolderId
            Write-Verbose "Message $($this._graphId) d�plac� vers $DestinationFolderId"
        }
        catch {
            Write-Error "Erreur lors du d�placement du message: $_"
        }
    }
    
    # Ajouter une m�thode Load() factice pour les attachments
    $obj | Add-Member -MemberType ScriptMethod -Name "Load" -Value {
        Write-Verbose "Load() appel� sur le message - donn�es d�j� charg�es"
    }
    
    $obj.PSObject.TypeNames.Insert(0, 'EwsCompat.Message')
    
    return $obj
}

#endregion

#region Gestion des Pi�ces Jointes

<#
.SYNOPSIS
    Cr�e un objet pi�ce jointe compatible EWS
    
.DESCRIPTION
    Fonction interne pour convertir une pi�ce jointe Graph en objet compatible EWS
#>
function New-EwsCompatAttachment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $GraphAttachment,
        
        [Parameter(Mandatory = $true)]
        [string]$MessageId
    )
    
    $obj = [PSCustomObject]@{
        Id = $GraphAttachment.Id
        Name = $GraphAttachment.Name
        ContentType = $GraphAttachment.ContentType
        Size = $GraphAttachment.Size
        IsInline = $GraphAttachment.IsInline
        _messageId = $MessageId
        _graphUser = $script:EwsCompat_CurrentUser
    }
    
    # Ajouter une m�thode pour sauvegarder la pi�ce jointe
    $obj | Add-Member -MemberType ScriptMethod -Name "Load" -Value {
        try {
            # R�cup�rer le contenu complet de la pi�ce jointe
            $fullAttachment = Get-MgUserMessageAttachment -UserId $this._graphUser -MessageId $this._messageId -AttachmentId $this.Id
            
            # Ajouter la propri�t� Content si disponible
            if ($fullAttachment.AdditionalProperties.ContainsKey('contentBytes')) {
                $this | Add-Member -MemberType NoteProperty -Name "ContentBytes" -Value $fullAttachment.AdditionalProperties['contentBytes'] -Force
            }
            
            Write-Verbose "Contenu de la pi�ce jointe charg�: $($this.Name)"
        }
        catch {
            Write-Error "Erreur lors du chargement de la pi�ce jointe: $_"
        }
    }
    
    # M�thode pour sauvegarder sur disque (simulant le comportement EWS)
    $obj | Add-Member -MemberType ScriptMethod -Name "SaveToFile" -Value {
        param([string]$Path)
        
        try {
            # Charger le contenu si pas d�j� fait
            if (-not $this.ContentBytes) {
                $this.Load()
            }
            
            # Sauvegarder le fichier
            $bytes = [System.Convert]::FromBase64String($this.ContentBytes)
            [System.IO.File]::WriteAllBytes($Path, $bytes)
            
            Write-Verbose "Pi�ce jointe sauvegard�e: $Path"
        }
        catch {
            Write-Error "Erreur lors de la sauvegarde de la pi�ce jointe: $_"
        }
    }
    
    $obj.PSObject.TypeNames.Insert(0, 'EwsCompat.Attachment')
    
    return $obj
}

<#
.SYNOPSIS
    Sauvegarde toutes les pi�ces jointes d'un message
    
.PARAMETER Message
    Objet message compatible EWS
    
.PARAMETER DestinationPath
    Chemin de destination pour les pi�ces jointes
    
.EXAMPLE
    Save-EwsCompatAttachments -Message $message -DestinationPath "C:\Temp\"
#>
function Save-EwsCompatAttachments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $Message,
        
        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )
    
    try {
        # Cr�er le r�pertoire si n�cessaire
        if (-not (Test-Path $DestinationPath)) {
            New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
        }
        
        $savedFiles = @()
        
        foreach ($attachment in $Message.Attachments) {
            $filePath = Join-Path $DestinationPath $attachment.Name
            
            # Charger et sauvegarder
            $attachment.Load()
            $attachment.SaveToFile($filePath)
            
            $savedFiles += $filePath
        }
        
        return $savedFiles
    }
    catch {
        Write-Error "Erreur lors de la sauvegarde des pi�ces jointes: $_"
        return @()
    }
}

#endregion

#region Envoi de Messages

<#
.SYNOPSIS
    Envoie un email via Graph (�quivalent � EmailMessage.SendAndSaveCopy)
    
.DESCRIPTION
    Simule la cr�ation et l'envoi d'un EmailMessage EWS via Microsoft Graph
    
.PARAMETER Subject
    Sujet de l'email
    
.PARAMETER Body
    Corps de l'email (texte ou HTML)
    
.PARAMETER BodyType
    Type de corps: "Text" ou "HTML" (d�faut: "HTML")
    
.PARAMETER ToRecipients
    Tableau d'adresses email des destinataires
    
.PARAMETER CcRecipients
    Tableau d'adresses email en copie (optionnel)
    
.PARAMETER Attachments
    Tableau de chemins de fichiers � attacher (optionnel)
    
.PARAMETER SaveToSentItems
    Si true, sauvegarde dans les �l�ments envoy�s (d�faut: true)
    
.EXAMPLE
    Send-EwsCompatMessage -Subject "Test" -Body "Hello" -ToRecipients @("user@domain.com")
    
.EXAMPLE
    Send-EwsCompatMessage -Subject "Report" -Body "<h1>Report</h1>" -BodyType "HTML" `
                          -ToRecipients @("user1@domain.com", "user2@domain.com") `
                          -CcRecipients @("cc@domain.com") `
                          -Attachments @("C:\report.pdf")
#>
function Send-EwsCompatMessage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Subject,
        
        [Parameter(Mandatory = $true)]
        [string]$Body,
        
        [Parameter(Mandatory = $false)]
        [ValidateSet("Text", "HTML")]
        [string]$BodyType = "HTML",
        
        [Parameter(Mandatory = $true)]
        [string[]]$ToRecipients,
        
        [Parameter(Mandatory = $false)]
        [string[]]$CcRecipients = @(),
        
        [Parameter(Mandatory = $false)]
        [string[]]$Attachments = @(),
        
        [Parameter(Mandatory = $false)]
        [bool]$SaveToSentItems = $true
    )
    
    if (-not $script:EwsCompat_CurrentUser) {
        throw "Utilisateur non initialis�. Appelez Initialize-EwsCompatConnection d'abord."
    }
    
    try {
        Write-Verbose "Pr�paration de l'envoi d'email via Graph"
        Write-Verbose "De: $script:EwsCompat_CurrentUser"
        Write-Verbose "�: $($ToRecipients -join ', ')"
        Write-Verbose "Sujet: $Subject"
        
        # Pr�parer les destinataires au format Graph
        $toRecipientsGraph = @()
        foreach ($recipient in $ToRecipients) {
            $toRecipientsGraph += @{
                EmailAddress = @{
                    Address = $recipient
                }
            }
        }
        
        # Pr�parer les destinataires en copie
        $ccRecipientsGraph = @()
        foreach ($recipient in $CcRecipients) {
            $ccRecipientsGraph += @{
                EmailAddress = @{
                    Address = $recipient
                }
            }
        }
        
        # Construire le message
        $message = @{
            Subject = $Subject
            Body = @{
                ContentType = $BodyType
                Content = $Body
            }
            ToRecipients = $toRecipientsGraph
        }
        
        # Ajouter CC si pr�sent
        if ($ccRecipientsGraph.Count -gt 0) {
            $message.CcRecipients = $ccRecipientsGraph
        }
        
        # G�rer les pi�ces jointes si pr�sentes
        if ($Attachments.Count -gt 0) {
            Write-Verbose "Traitement de $($Attachments.Count) pi�ce(s) jointe(s)"
            $message.Attachments = @()
            
            foreach ($attachmentPath in $Attachments) {
                if (Test-Path $attachmentPath) {
                    $fileName = Split-Path $attachmentPath -Leaf
                    $fileBytes = [System.IO.File]::ReadAllBytes($attachmentPath)
                    $base64 = [System.Convert]::ToBase64String($fileBytes)
                    
                    $message.Attachments += @{
                        "@odata.type" = "#microsoft.graph.fileAttachment"
                        Name = $fileName
                        ContentBytes = $base64
                    }
                    
                    Write-Verbose "Pi�ce jointe ajout�e: $fileName"
                }
                else {
                    Write-Warning "Fichier non trouv�: $attachmentPath"
                }
            }
        }
        
        # Envoyer le message
        $params = @{
            UserId = $script:EwsCompat_CurrentUser
            Message = $message
            SaveToSentItems = $SaveToSentItems
        }
        
        Send-MgUserMail @params
        
        Write-Verbose "Email envoy� avec succ�s via Graph"
        
        return @{
            Success = $true
            Message = "Email envoy� avec succ�s"
        }
    }
    catch {
        Write-Error "Erreur lors de l'envoi de l'email: $_"
        Write-Verbose "D�tails: $($_.Exception.Message)"
        
        return @{
            Success = $false
            Error = $_.Exception.Message
        }
    }
}

#endregion

#region Fonctions Utilitaires

<#
.SYNOPSIS
    Obtient le nombre de messages dans un dossier
    
.PARAMETER FolderId
    ID du dossier ou objet dossier compatible EWS
    
.EXAMPLE
    $count = Get-EwsCompatFolderMessageCount -FolderId $folder.Id
#>
function Get-EwsCompatFolderMessageCount {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        $FolderId
    )
    
    try {
        # Extraire l'ID si c'est un objet
        if ($FolderId -is [PSCustomObject] -and $FolderId.Id) {
            return $FolderId.TotalCount
        }
        
        # Sinon r�cup�rer le dossier
        $folder = Get-MgUserMailFolder -UserId $script:EwsCompat_CurrentUser -MailFolderId $FolderId
        return $folder.TotalItemCount
    }
    catch {
        Write-Error "Erreur lors de la r�cup�ration du nombre de messages: $_"
        return 0
    }
}

#endregion

# Export des fonctions
Export-ModuleMember -Function @(
    'Initialize-EwsCompatConnection',
    'Get-EwsCompatFolder',
    'Get-EwsCompatMessages',
    'Save-EwsCompatAttachments',
    'Get-EwsCompatFolderMessageCount'
)