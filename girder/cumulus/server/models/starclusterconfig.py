import cherrypy

from girder.models.model_base import AccessControlledModel
from girder.constants import AccessType
from bson.objectid import ObjectId
import cumulus
from .base import BaseModel

class Starclusterconfig(BaseModel):

    def initialize(self):
        self.name = 'starclusterconfigs'

    def validate(self, doc):
        return doc

    def create(self, config):

        print self.get_group_id()

        group = {
            '_id': ObjectId(self.get_group_id())
        }
        doc  = self.setGroupAccess(config, group, level=AccessType.ADMIN, save=True)

        return doc



