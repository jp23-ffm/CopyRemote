# Import du module de wrappers
Import-Module .\EwsGraphWrappers.psm1 -Force

<#
.SYNOPSIS
    Envoie un email via Graph (version migrée de F_SentMail)
    
.DESCRIPTION
    Cette fonction remplace l'ancienne version EWS par une version Graph
    tout en conservant la même signature de fonction.
#>
Function F_SentMail {
    param(
        [Parameter(Mandatory = $true)] [string]$S_MailOfService,
        [Parameter(Mandatory = $false)] [string]$S_LoginExchange,
        [Parameter(Mandatory = $false)] [string]$S_Domain,
        [Parameter(Mandatory = $false)] [string]$S_PasswordExchange,
        [Parameter(Mandatory = $true)] [string]$S_Connectionstring,
        [Parameter(Mandatory = $true)] [string]$S_Body,
        [Parameter(Mandatory = $true)] [string]$S_SubjectMail,
        [Parameter(Mandatory = $true)] [array]$A_ToRecipients
    )
    
    Try {
        # === CHANGEMENT : Initialisation Graph au lieu de EWS ===
        $connectionResult = Initialize-EwsCompatConnection -UserEmail $S_MailOfService
        
        if (-not $connectionResult.Success) {
            Write-Error "Erreur lors de l'initialisation de la connexion Graph"
            Return @(1, $connectionResult.Error)
        }
        
        Write-Verbose "Connexion Graph initialisée pour: $S_MailOfService"
        
        # === CHANGEMENT : Envoi via Graph au lieu de EWS ===
        # Conversion du tableau de destinataires (si nécessaire)
        $toRecipients = @()
        foreach ($recipient in $A_ToRecipients) {
            # Si c'est déjà une string, on l'ajoute directement
            if ($recipient -is [string]) {
                $toRecipients += $recipient
            }
            # Si c'est un objet avec une propriété Address ou EmailAddress
            elseif ($recipient.Address) {
                $toRecipients += $recipient.Address
            }
            elseif ($recipient.EmailAddress) {
                $toRecipients += $recipient.EmailAddress
            }
        }
        
        # Envoi du message
        $result = Send-EwsCompatMessage -Subject $S_SubjectMail `
                                        -Body $S_Body `
                                        -BodyType "HTML" `
                                        -ToRecipients $toRecipients `
                                        -SaveToSentItems $true
        
        if ($result.Success) {
            Write-Verbose "Email envoyé avec succès"
            Return @(0, $null)
        }
        else {
            Write-Error "Échec de l'envoi: $($result.Error)"
            Return @(1, $result.Error)
        }
    }
    Catch {
        Write-Error "Erreur dans F_SentMail: $_"
        Return @(1, $_.Exception.Message)
    }
}


<#
.SYNOPSIS
    Vérifie et envoie un email de gouvernance (version migrée de R_CheckSendingGovernance)
    
.DESCRIPTION
    Cette fonction remplace l'ancienne version EWS par une version Graph.
    Elle récupère des informations depuis la base de données et envoie un email
    de validation de commande à l'équipe de gouvernance.
#>
Function R_CheckSendingGovernance {
    param(
        [Parameter(Mandatory = $true)] [string]$S_Mail,
        [Parameter(Mandatory = $false)] [string]$S_LoginExchange,
        [Parameter(Mandatory = $false)] [string]$S_PasswordExchange,
        [Parameter(Mandatory = $false)] [string]$S_Domain,
        [Parameter(Mandatory = $true)] [string]$S_Connectionstring,
        [Parameter(Mandatory = $true)] [string]$S_UrlSP
    )
    
    # Connexion ADODB (inchangée)
    $I_adOpenStatic = 3
    $I_adLockOptimistic = 3
    $O_Connection = New-Object -ComObject ADODB.Connection
    $O_Connection.Open($S_Connectionstring)
    $O_RecordsetRead = New-Object -ComObject ADODB.Recordset
    $O_RecordsetReadSecond = New-Object -ComObject ADODB.Recordset
    $O_RecordsetUpdate = New-Object -ComObject ADODB.Recordset
    
    # Requête pour récupérer les commandes en attente de validation
    $O_RecordsetRead.Open(
        "select * from T_PurchaseCart where T_PurchaseCart_StateInt = 25 and T_PurchaseCart_Provider = 'DELL' and (T_PurchaseCart_Country = 'FR')", 
        $O_Connection, 
        $I_adOpenStatic, 
        $I_adLockOptimistic
    )
    
    If (-Not $O_RecordsetRead.EOF) {
        $SetFormDigest = F_SetFormDigest
        $O_RecordsetRead.MoveFirst()
        
        Do {
            # === CHANGEMENT : Initialisation Graph au lieu de EWS ===
            $connectionResult = Initialize-EwsCompatConnection -UserEmail $S_Mail
            
            if (-not $connectionResult.Success) {
                Write-Host -ForegroundColor Red "Erreur lors de l'initialisation de la connexion Graph"
                Continue
            }
            
            # Récupération des informations de la commande
            $S_message_Subject = "Order approved for the project nammed : " + 
                                $O_RecordsetRead.Fields.Item("T_PurchaseCart_ProjectName").Value
            
            # Requête pour récupérer les détails du demandeur
            $O_RecordsetReadSecond.Open(
                "select T_LdapLoginTranslate_Mail, T_LdapLoginTranslate_Name from T_LdapLoginTranslate where T_LdapLoginTranslate_Login = '" + 
                $O_RecordsetRead.Fields.Item("T_PurchaseCart_Requester").Value + "'", 
                $O_Connection, 
                $I_adOpenStatic, 
                $I_adLockOptimistic
            )
            
            $O_RecordsetReadSecond.MoveFirst()
            $S_MailToRequester = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Mail").Value
            $S_NameToRequester = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Name").Value
            $O_RecordsetReadSecond.Close()
            
            # Requête pour récupérer les détails du validateur
            $O_RecordsetReadSecond.Open(
                "select T_LdapLoginTranslate_Mail, T_LdapLoginTranslate_Name from T_LdapLoginTranslate where T_LdapLoginTranslate_Login = '" + 
                $O_RecordsetRead.Fields.Item("T_PurchaseCart_ValidateManagerLevel1").Value + "'", 
                $O_Connection, 
                $I_adOpenStatic, 
                $I_adLockOptimistic
            )
            
            $S_MailToValidator = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Mail").Value
            $S_NameToValidator = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Name").Value
            $O_RecordsetReadSecond.Close()
            
            # Vérifier s'il y a un délégué
            If ($O_RecordsetRead.Fields.Item("T_PurchaseCart_Delegation").Value -ne "-") {
                $O_RecordsetReadSecond.Open(
                    "select T_LdapLoginTranslate_Mail, T_LdapLoginTranslate_Name from T_LdapLoginTranslate where T_LdapLoginTranslate_Login = '" + 
                    $O_RecordsetRead.Fields.Item("T_PurchaseCart_Delegation").Value + "'", 
                    $O_Connection, 
                    $I_adOpenStatic, 
                    $I_adLockOptimistic
                )
                
                $S_MailToDelegate = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Mail").Value
                $S_NameToDelegate = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Name").Value
                $O_RecordsetReadSecond.Close()
            }
            
            # Récupérer les pièces jointes depuis la base de données
            $O_RecordsetReadSecond.Open(
                "SELECT T_PurchaseMailReceived.T_PurchaseMailReceived_QuotationValid, T_PurchaseMailReceivedAttachment.T_PurchaseMailReceivedAttachment_id, " + 
                "T_PurchaseMailReceivedAttachment.T_PurchaseMailReceivedAttachment_AttachmentName, " + 
                "T_PurchaseMailReceivedAttachment.T_PurchaseMailReceivedAttachment_RamdomFileName, " + 
                "T_PurchaseMailReceived.T_PurchaseMailReceived_Body, " + 
                "T_PurchaseMailReceived.T_PurchaseMailReceived_Subject, " + 
                "T_PurchaseMailReceived.T_PurchaseMailReceived_AttachmentCount, " + 
                "T_PurchaseMailReceived.T_PurchaseMailReceived_T_PurchaseCart_ID " + 
                "FROM T_PurchaseMailReceived " + 
                "INNER JOIN T_PurchaseMailReceivedAttachment ON T_PurchaseMailReceived.T_PurchaseMailReceived_ID = " + 
                "T_PurchaseMailReceivedAttachment.T_PurchaseMailReceivedAttachment_T_PurchaseMailReceived_ID " + 
                "where T_PurchaseMailReceived_QuotationValid = 'YES' And " + 
                "T_PurchaseMailReceived_T_PurchaseCart_ID = '" + 
                $O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value + "'",
                $O_Connection, 
                $I_adOpenStatic, 
                $I_adLockOptimistic
            )
            
            $O_RecordsetReadSecond.MoveFirst()
            $A_FileAttachment = @()
            $S_HistoryMail = $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceived_Body").Value
            
            Do {
                # Construire le chemin des pièces jointes
                $O_PSObject = New-Object PSObject
                Copy-Item `
                    ("\\DFS\root\common\infrads\Portal_Indus\WebSite\wwwroot\Purchase\Attachments\" + 
                    $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_RamdomFileName").Value + ".pdf") `
                    ("\\DFS\root\common\infrads\Portal_Indus\Scripts\Purchase\Attachments\" + 
                    $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_AttachmentName").Value)
                
                Add-Member -InputObject $O_PSObject -MemberType NoteProperty -Name A_FileAttachment -Value `
                    $("\\DFS\root\common\infrads\Portal_Indus\Scripts\Purchase\Attachments\" + 
                    $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_AttachmentName").Value)
                
                Add-Member -InputObject $O_PSObject -MemberType NoteProperty -Name T_PurchaseMailReceivedAttachment_id -Value `
                    $($O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_id").Value)
                
                $A_FileAttachment += $O_PSObject
                $O_RecordsetReadSecond.MoveNext()
                
            } Until ($O_RecordsetReadSecond.EOF)
            
            $O_RecordsetReadSecond.Close()
            
            # Construction du corps de l'email
            $O_message_Body = "Hello, <br><br>The quotation has been added in the form of the governance order server." + 
                            "<br>This order has been approved by $S_NameToValidator from the workflow purchase" + 
                            "<br>The requester $S_NameToRequester is in charge of this order.<br>The budget assign is :" + 
                            "<b>" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_Budget").Value + 
                            "</b><br><br><br>Below the history from the mail with attachment quotation." + 
                            "<br><br><br><br><br>Regards,<br>Portal Indus WorkFlow Purchase<br>emea.purchase.digital.workflow@bnpparibas.com<br><br><br>$S_HistoryMail"
            
            # Préparer les destinataires
            $S_ToRecipients = @()
            ForEach ($S_A_FileAttachment in $A_FileAttachment) {
                # Récupérer les informations du formulaire de commande
                $F_GetInfoPurchaseFormGov = F_GetInfoPurchaseFormGov -S_Connectionstring $S_Connectionstring `
                    -S_T_PurchaseSettings_Id $($O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value) `
                    -S_UrlSP $S_UrlSP `
                    -S_PathFileQuotation $($S_A_FileAttachment.A_FileAttachment) `
                    -I_CostOrder $I_CostOrder `
                    -F_GetInfoPurchaseFormGov $F_GetInfoPurchaseFormGov
                
                Write-Host -ForegroundColor Red "ici"
                Write-Host -ForegroundColor Green $F_GetInfoPurchaseFormGov
                Write-Host -ForegroundColor Red "ici"
                
                If ($I_FlagIdFormOrder -eq 1) {
                    Write-Host -ForegroundColor Red "insert line in SP"
                    $F_InsertDataFormSP = F_InsertDataFormSP -S_TableSP "OrderForm" `
                        -F_GetInfoPurchaseFormGov $F_GetInfoPurchaseFormGov `
                        -S_TypeSP "OrderForm_x0020_testListItem"
                    
                    $O_RecordsetUpdate.Open(
                        "update T_PurchaseCart set T_PurchaseCart_IdSpGov = $($F_InsertDataFormSP.d.Id) where T_PurchaseCart_ID = '" + 
                        $O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value + "'", 
                        $O_Connection, 
                        $I_adOpenStatic, 
                        $I_adLockOptimistic
                    )
                    
                    $I_FlagIdFormOrder = 0
                }
                
                Write-Host -ForegroundColor Green "Stdout insert line sharepoint"
                Write-Host -ForegroundColor Green $F_InsertDataFormSP
                
                If ($($F_InsertDataFormSP.d.Id)) {
                    F_AddAttachments -S_UrlSP $S_UrlSP `
                        -S_ListName "OrderForm" `
                        -I_ItemId $($F_InsertDataFormSP.d.Id) `
                        -S_SourcePath $($S_A_FileAttachment.A_FileAttachment) `
                        -verbose
                    
                    $O_RecordsetUpdate.Open(
                        "update T_PurchaseMailReceivedAttachment set T_PurchaseMailReceivedAttachment_IdSpGov = $($F_InsertDataFormSP.d.Id) " + 
                        "where T_PurchaseMailReceivedAttachment_id = $($S_A_FileAttachment.T_PurchaseMailReceivedAttachment_id)", 
                        $O_Connection, 
                        $I_adOpenStatic, 
                        $I_adLockOptimistic
                    )
                }
                Else {
                    R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [Push Data Form Governance]" `
                        -MsgError "None ID receive, please check or add manually these information<br>$F_GetInfoPurchaseFormGov<br>ID Order:"+$($O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value)+"<br>$($S_A_FileAttachment.A_FileAttachment)"
                    
                    R_WriteLogs -S_LogInfo "ERROR processing WorkFlow Order [Push Data Form Governance]" `
                        -S_ScriptName $S_ScriptName `
                        -S_LogFile $S_LogFullPath `
                        -S_LogSeverity "Error"
                }
            }
            
            Write-Host -ForegroundColor Yellow "update price $I_CostOrder"
            $data = (ConvertTo-Json @{
                __metadata = @{type= "SP.Data.OrderForm_x0020_testListItem"}
                jlvi = "$I_CostOrder"
            })
            
            $Updated = F_UpdateListItem -itemURI $($F_InsertDataFormSP.d.__metadata.uri) `
                -PropertyName $data `
                -SetFormDigest $SetFormDigest
            
            Write-Host -ForegroundColor Yellow $data
            
            # === CHANGEMENT : Envoi via Graph au lieu de EWS ===
            # Extraire les chemins de fichiers pour les pièces jointes
            $attachmentPaths = @()
            foreach ($fileAttachment in $A_FileAttachment) {
                $attachmentPaths += $fileAttachment.A_FileAttachment
            }
            
            # Préparer les destinataires
            ForEach ($S_ToRecipients in $A_MailToGovernance) {
                $toRecipients += $S_ToRecipients
            }
            
            # Ajouter les CC
            $ccRecipients = @($S_MailToRequester, $S_MailToValidator)
            
            If ($O_RecordsetRead.Fields.Item("T_PurchaseCart_Delegation").Value -ne "-") {
                $ccRecipients += $S_MailToDelegate
            }
            
            # Envoi du message
            $result = Send-EwsCompatMessage -Subject $S_message_Subject `
                                            -Body $O_message_Body `
                                            -BodyType "HTML" `
                                            -ToRecipients $toRecipients `
                                            -CcRecipients $ccRecipients `
                                            -Attachments $attachmentPaths `
                                            -SaveToSentItems $true
            
            if ($result.Success) {
                Write-Host -ForegroundColor Green "Email envoyé avec succès"
                
                # Nettoyer les fichiers temporaires
                Start-Sleep -Seconds 10
                ForEach ($S_A_FileAttachment in $A_FileAttachment) {
                    Remove-Item $($S_A_FileAttachment.A_FileAttachment)
                }
                
                # Mettre à jour le statut dans la base de données
                $O_RecordsetUpdate.Open(
                    "update T_PurchaseCart set T_PurchaseCart_StateInt = '30', T_PurchaseCart_StateString = 'ORDER SENT GOVERNANCE' " + 
                    "where T_PurchaseCart_ID = '" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value + "'", 
                    $O_Connection, 
                    $I_adOpenStatic, 
                    $I_adLockOptimistic
                )
            }
            else {
                Write-Host -ForegroundColor Red "Erreur lors de l'envoi: $($result.Error)"
            }
            
            $O_RecordsetRead.MoveNext()
            
        } Until ($O_RecordsetRead.EOF)
    }
    
    $O_RecordsetRead.Close()
    $O_Connection.Close()
}


<#
===========================================
EXEMPLE D'UTILISATION
===========================================
#>

# IMPORTANT: Vous devez d'abord vous connecter à Microsoft Graph
Connect-MgGraph -Scopes "Mail.ReadWrite", "Mail.ReadWrite.Shared", "Mail.Send", "Mail.Send.Shared"

# Import du module de wrappers
Import-Module .\EwsGraphWrappers.psm1 -Force

# Exemple 1: Envoi simple via F_SentMail
$result = F_SentMail -S_MailOfService "service@domain.com" `
                     -S_Connectionstring $S_Connectionstring `
                     -S_Body "<h1>Test</h1><p>Message de test</p>" `
                     -S_SubjectMail "Test depuis Graph" `
                     -A_ToRecipients @("user1@domain.com", "user2@domain.com")

If ($result[0] -eq 0) {
    Write-Host "Email envoyé avec succès"
}
Else {
    Write-Host "Erreur: $($result[1])"
}

# Exemple 2: Traitement automatique avec R_CheckSendingGovernance
R_CheckSendingGovernance -S_Mail "workflow@domain.com" `
                         -S_Connectionstring $S_Connectionstring `
                         -S_UrlSP "https://sharepoint.domain.com"