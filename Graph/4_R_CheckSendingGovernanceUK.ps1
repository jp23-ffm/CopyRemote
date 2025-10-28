Function R_CheckSendingGovernanceUK {
    param(
        [Parameter(Mandatory = $true)] [string]$S_Mail,
        [Parameter(Mandatory = $false)] [string]$S_LoginExchange,
        [Parameter(Mandatory = $false)] [string]$S_PasswordExchange,
        [Parameter(Mandatory = $false)] [string]$S_Domain,
        [Parameter(Mandatory = $true)] [string]$S_Connectionstring
    )
    
    # Connexion ADODB (inchangée)
    $I_adOpenStatic = 3
    $I_adLockOptimistic = 3
    $O_Connection = New-Object -ComObject ADODB.Connection
    $O_Connection.Open($S_Connectionstring)
    $O_RecordsetRead = New-Object -ComObject ADODB.Recordset
    $O_RecordsetReadSecond = New-Object -ComObject ADODB.Recordset
    $O_RecordsetUpdate = New-Object -ComObject ADODB.Recordset
    
    # Récupérer les commandes en attente pour UK et US
    $O_RecordsetRead.Open(
        "select * from T_PurchaseCart where T_PurchaseCart_StateInt = 25 and T_PurchaseCart_Provider = 'DELL' and (T_PurchaseCart_Country = 'United Kingdom' or T_PurchaseCart_Country = 'GB')", 
        $O_Connection, 
        $I_adOpenStatic, 
        $I_adLockOptimistic
    )
    
    If (-Not $O_RecordsetRead.EOF) {
        $O_RecordsetRead.MoveFirst()
        $I_TotalCommands = 0
        $I_ProcessedCommands = 0
        
        # Compter le nombre total
        Do {
            $I_TotalCommands++
            $O_RecordsetRead.MoveNext()
        } Until ($O_RecordsetRead.EOF)
        
        Write-Host -ForegroundColor Cyan "🚀 $I_TotalCommands commandes UK/US à traiter"
        $O_RecordsetRead.MoveFirst()
        
        Do {
            Try {
                # === CHANGEMENT : Initialisation Graph au lieu de EWS ===
                $connectionResult = Initialize-EwsCompatConnection -UserEmail $S_Mail
                
                if (-not $connectionResult.Success) {
                    Write-Host -ForegroundColor Red "Erreur lors de l'initialisation de la connexion Graph"
                    Throw "Graph connection failed"
                }
                
                # Récupérer les paramètres de configuration
                $O_RecordsetReadSecond.Open(
                    "select T_PurchaseSettings_Value from T_PurchaseSettings where T_PurchaseSettings_Type = 'MailSentToGovernanceUK'", 
                    $O_Connection, 
                    $I_adOpenStatic, 
                    $I_adLockOptimistic
                )
                
                $O_RecordsetReadSecond.MoveFirst()
                $A_MailToGovernance = $($O_RecordsetReadSecond.Fields.Item("T_PurchaseSettings_Value").Value).split(",")
                $O_RecordsetReadSecond.Close()
                
                # Récupérer les détails du demandeur
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
                
                # Récupérer les détails du validateur
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
                $S_MailToDelegate = $null
                $S_NameToDelegate = $null
                
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
                    
                    # Copier les fichiers depuis WebSite vers Scripts
                    Copy-Item `
                        ("\\DFS\WebSite\wwwroot\Purchase\Attachment\" + 
                        $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_RamdomFileName").Value + ".pdf") `
                        ("\\DFS\Scripts\Purchase\Attachments\" + 
                        $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_AttachmentName").Value)
                    
                    Add-Member -InputObject $O_PSObject -MemberType NoteProperty -Name A_FileAttachment -Value `
                        $("\\DFS\Scripts\Purchase\Attachments\" + 
                        $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_AttachmentName").Value)
                    
                    Add-Member -InputObject $O_PSObject -MemberType NoteProperty -Name T_PurchaseMailReceivedAttachment_id -Value `
                        $($O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_id").Value)
                    
                    $A_FileAttachment += $O_PSObject
                    $O_RecordsetReadSecond.MoveNext()
                    
                } Until ($O_RecordsetReadSecond.EOF)
                
                $O_RecordsetReadSecond.Close()
                
                # Construction du corps de l'email
                $O_message_Body = "Hello, <br><br>Could you please take in charge this quotation ?" + 
                                "<br>This order has been approved by $S_NameToValidator from the purchase workflow on FR side" + 
                                "<br>The requester is $S_NameToRequester .<br>Assigned Cost center is : <b>BAU</b>, Domain : " +
                                "<b>" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_BudgetDom").Value + "</b>, Cost Nature : " +
                                "<b>" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_BudgetCosNat").Value + "</b><br><br>" +
                                "<b>" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_BudgetCosNat").Value + "</b><br><br>" +
                                "Business sponsor is : " + $O_RecordsetRead.Fields.Item("T_PurchaseCart_RequesterTeam").Value + 
                                " For the TEAM : " + $O_RecordsetRead.Fields.Item("T_PurchaseCart_RequesterNameTeam").Value + 
                                "<br><br>This Mail has been sent by a bot, When you will have to raise a Purchase request in ITSM please add in the " +
                                "short description : '" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_ProjectName").Value + " [" + 
                                $O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value + "]'" + 
                                "<br><br><br><br>Regards,<br>Portal Indus WorkFlow Purchase<br>emea.purchase.digital.workflow@bnpparibas.com<br>" +
                                "<br><br>$S_HistoryMail"
                
                # Préparer le sujet
                $S_message_Subject = "[FOR UK SOURCING] Order approved for the project nammed : " + 
                                    $O_RecordsetRead.Fields.Item("T_PurchaseCart_ProjectName").Value
                
                # === CHANGEMENT : Envoi via Graph au lieu de EWS ===
                # Préparer les destinataires To
                $toRecipients = @()
                ForEach ($recipient in $A_MailToGovernance) {
                    $toRecipients += $recipient.Trim()
                }
                
                # Préparer les destinataires Cc
                $ccRecipients = @()
                If ($S_MailToRequester -ne "KO") {
                    $ccRecipients += $S_MailToRequester
                }
                $ccRecipients += $S_MailToValidator
                $ccRecipients += "mei.jeoubi@xxx.com"
                $ccRecipients += "syin.courdan@xxx.com"
                $ccRecipients += "fice.ous@xxx.com"
                $ccRecipients += "dl.uk.datacentre@uk.xxx.com"
                
                If ($O_RecordsetRead.Fields.Item("T_PurchaseCart_Delegation").Value -ne "-") {
                    $ccRecipients += $S_MailToDelegate
                }
                
                # Extraire les chemins de fichiers pour les pièces jointes
                $attachmentPaths = @()
                foreach ($fileAttachment in $A_FileAttachment) {
                    Write-Host "R_CheckSendingGovernanceUK: $($fileAttachment.A_FileAttachment)"
                    $attachmentPaths += $fileAttachment.A_FileAttachment
                }
                
                # Envoyer le message via Graph
                $result = Send-EwsCompatMessage -Subject $S_message_Subject `
                                                -Body $O_message_Body `
                                                -BodyType "HTML" `
                                                -ToRecipients $toRecipients `
                                                -CcRecipients $ccRecipients `
                                                -Attachments $attachmentPaths `
                                                -SaveToSentItems $true
                
                if ($result.Success) {
                    Write-Host -ForegroundColor Green "Email envoyé avec succès pour commande $($O_RecordsetRead.Fields.Item('T_PurchaseCart_ID').Value)"
                    
                    # Pause et nettoyage
                    Start-Sleep -Seconds 10
                    ForEach ($S_A_FileAttachment in $A_FileAttachment) {
                        Remove-Item $($S_A_FileAttachment.A_FileAttachment) -ErrorAction SilentlyContinue
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
                
                $I_ProcessedCommands++
                
            }
            Catch {
                # === GESTION D'ERREUR : FAIL-FAST ===
                Write-Host -ForegroundColor Red "Erreur Graph détectée: $_"
                Write-Host -ForegroundColor Red "Arrêt du traitement. $I_ProcessedCommands commandes traitées sur $I_TotalCommands."
                
                # Alerte
                R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckSendingGovernanceUK] - Graph timeout/error" `
                                -MsgError "Erreur détectée après $I_ProcessedCommands commandes traitées. Commandes restantes: $($I_TotalCommands - $I_ProcessedCommands). Erreur: $($_.Exception.Message)"
                
                # Fermer les recordsets s'ils sont ouverts
                Try { $O_RecordsetReadSecond.Close() } Catch {}
                
                # SORTIE IMMÉDIATE
                Break
            }
            
            $O_RecordsetRead.MoveNext()
            
        } Until ($O_RecordsetRead.EOF)
        
        Write-Host -ForegroundColor Cyan "Traitement UK terminé : $I_ProcessedCommands/$I_TotalCommands commandes traitées"
    }
    Else {
        Write-Host -ForegroundColor Green "Aucune commande UK/US en attente (StateInt = 25)"
    }
    
    # Fermeture propre
    $O_RecordsetRead.Close()
    $O_Connection.Close()
}



<#
===========================================
EXEMPLE D'UTILISATION
===========================================
#>

# IMPORTANT: Connexion à Microsoft Graph avec Application permissions
Connect-MgGraph -ClientId $ClientId -TenantId $TenantId -CertificateThumbprint $Thumbprint

# Import du module de wrappers
Import-Module .\EwsGraphWrappers.psm1 -Force

# Définir vos variables
$S_Connectionstring = "Provider=SQLOLEDB;Data Source=...;Initial Catalog=...;User ID=...;Password=..."

# Appel de la fonction
R_CheckSendingGovernanceUK -S_Mail "emea.purchase.digital.workflow@bnpparibas.com" `
                           -S_LoginExchange "dummy" `
                           -S_PasswordExchange "dummy" `
                           -S_Domain "dummy" `
                           -S_Connectionstring $S_Connectionstring

