
from django import forms
from .models import ServerUnique
import datetime


# Form for Business Continuity Information
class BusinessContinuityInformationForm(forms.ModelForm):
    
    # Choices for priority asset, live play and cluster fields
    CHOICES_LIVE_PLAY = [
        ('YES', 'YES'),
        ('NO', 'NO'),
        ('EMPTY', 'EMPTY'),
    ]

    # Field for Priority Asset
    priority_asset = forms.ChoiceField( 
        choices=CHOICES_LIVE_PLAY,
        required=False,
        label="Is a Priority Asset",
        widget=forms.Select(attrs={'class': 'select-box'})
    )

    # Field for the Live Play status
    in_live_play = forms.ChoiceField( 
        choices=CHOICES_LIVE_PLAY,
        required=False,
        label="In Live Play",
        widget=forms.Select(attrs={'class': 'select-box'})
    )
    
    # Field for Cluster
    cluster = forms.ChoiceField( 
        choices=CHOICES_LIVE_PLAY,
        required=False,
        label="Cluster",
        widget=forms.Select(attrs={'class': 'select-box'})
    )

    # Field for Action During Live Play History
    action_during_lp_history = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'readonly': 'readonly', 'class': 'history-display'}),
        required=False,
        label="Action During Live Play Historic"
    )
    
    # Field for Annotation History
    annotation_history = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'readonly': 'readonly', 'class': 'history-display'}),
        required=False,
        label="Annotation Historic"
    )
    

    # Field for the BC exception: the server is left alone by BC rules on the affected site
    bc_exception = forms.ChoiceField(
        choices=CHOICES_LIVE_PLAY,
        required=False,
        label="BC Exception",
        widget=forms.Select(attrs={'class': 'select-box'})
    )

    # Meta class to specify the model and fields
    class Meta:
        model = ServerUnique
        fields = ['priority_asset', 'in_live_play', 'action_during_lp', 'annotation', 'cluster', 'cluster_type', 'bc_exception']


    def __init__(self, *args, loggedonuser=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.loggedonuser = loggedonuser

        # Store original values for comparison
        self.previous_priority_asset = self.instance.priority_asset
        self.previous_in_live_play = self.instance.in_live_play
        self.previous_cluster = self.instance.cluster
        self.previous_cluster_type = self.instance.cluster_type
        self.previous_bc_exception = self.instance.bc_exception
        self.previous_action_during_lp = self.instance.action_during_lp
        self.previous_action_during_lp_history = self.instance.action_during_lp_history
        self.previous_annotation = self.instance.annotation
        self.previous_annotation_history = self.instance.annotation_history
            
        if self.instance and self.instance.pk:
            self.fields['action_during_lp_history'].initial = self.instance.action_during_lp_history
            self.fields['annotation_history'].initial = self.instance.annotation_history

        # Update form attributes for action_during_lp, annotation fields and cluster
        self.fields['action_during_lp'].widget.attrs.update({ 
            'placeholder': 'Enter the Action During LP...',
            'rows': 1
        })
            
        self.fields['annotation'].widget.attrs.update({ 
            'placeholder': 'Enter the Annotation...',
            'rows': 1
        })

        self.fields['cluster_type'].widget.attrs.update({ 
            'placeholder': 'Enter the Cluster Type...',
            'rows': 1
        })
        

    # Save method to handle form submission
    def save(self, commit=True):

        instance = super().save(commit=False)

        now_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_usr = self.loggedonuser
        now_str = f"[{now_date} - {now_usr}]"
        
        # Create a new history entry
        history_entry = {
            "date": now_date,
            "user": now_usr,
            "fromsource": "Single Edit",
            "changes": {}
        }

        # Update the Priority Asset field
        priority_asset_choice = self.cleaned_data.get('priority_asset')
        if priority_asset_choice:
            instance.priority_asset = priority_asset_choice
        else:  # nothing chosen: keep the stored value
            instance.priority_asset = self.previous_priority_asset
        history_entry["changes"]["priority_asset"] = {
            "old": self.previous_priority_asset,
            "new": self.instance.priority_asset if self.previous_priority_asset != self.instance.priority_asset else 'Not set or not modified'
        }
            
        # Update the Live Play status field
        in_live_play_choice = self.cleaned_data.get('in_live_play')
        if in_live_play_choice:
            instance.in_live_play = in_live_play_choice
        else:  # nothing chosen: keep the stored value
            instance.in_live_play = self.previous_in_live_play
        history_entry["changes"]["in_live_play"] = {
            "old": self.previous_in_live_play,
            "new": self.instance.in_live_play if self.previous_in_live_play != self.instance.in_live_play else 'Not set or not modified'
        }

        # Update the Action During Live Play and Action During Live Play History fields
        action_during_lp = self.cleaned_data.get('action_during_lp')
        if action_during_lp and action_during_lp != self.previous_action_during_lp:  # Check for non-empty string and compare with the previous value
            instance.action_during_lp = action_during_lp
            instance.action_during_lp_history = f"{now_str} {action_during_lp}\n" + (instance.action_during_lp_history or '')
            history_entry["changes"]["action_during_lp"] = {
                "info": "Has been edited, check its history"
            }
        else:
            instance.action_during_lp = self.previous_action_during_lp
            instance.action_during_lp_history = self.previous_action_during_lp_history
            history_entry["changes"]["action_during_lp"] = {
                "info": "Not set or not modified"
            }            

        # Update the Annotation and Annotation History fields
        annotation = self.cleaned_data.get('annotation')
        if annotation and annotation != self.previous_annotation:  # Check for non-empty string and compare with the previous value
            instance.annotation = annotation
            instance.annotation_history = f"{now_str} {annotation}\n" + (instance.annotation_history or '')
            history_entry["changes"]["annotation"] = {
                "info": "Has been edited, check its history"
            }            
        else:
            instance.annotation = self.previous_annotation
            instance.annotation_history = self.previous_annotation_history
            history_entry["changes"]["annotation"] = {
                "info": "Not set or not modified"
            }                 
        
        # Update the Cluster field
        cluster = self.cleaned_data.get('cluster')
        if cluster:
            instance.cluster = cluster
        else:  # nothing chosen: keep the stored value
            instance.cluster = self.previous_cluster
        history_entry["changes"]["cluster"] = {
            "old": self.previous_cluster,
            "new": self.instance.cluster if self.previous_cluster != self.instance.cluster else 'Not set or not modified'
        }

        # Update the Cluster Type field
        cluster_type = self.cleaned_data.get('cluster_type')
        if cluster_type:
            instance.cluster_type = cluster_type
        history_entry["changes"]["cluster_type"] = {
            "old": self.previous_cluster_type,
            "new": self.instance.cluster_type if self.previous_cluster_type != self.instance.cluster_type else 'Not set or not modified'
        }

        # Update the BC Exception field
        bc_exception_choice = self.cleaned_data.get('bc_exception')
        if bc_exception_choice:
            instance.bc_exception = bc_exception_choice
        else:
            instance.bc_exception = self.previous_bc_exception
        history_entry["changes"]["bc_exception"] = {
            "old": self.previous_bc_exception,
            "new": instance.bc_exception if self.previous_bc_exception != instance.bc_exception else 'Not set or not modified'
        }

        # Only add the history entry if there are changes
        if history_entry["changes"]:
            print("ici")
            instance.global_history.append(history_entry)
            
        if commit:
            instance.save()
        return instance


# Form for CSV file upload
class CsvUploadForm(forms.Form):
    csv_file = forms.FileField(label="Select a CSV file", widget=forms.FileInput(attrs={'accept': '.csv'}))
    

