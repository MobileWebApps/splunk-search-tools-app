class BucketType(object):
    PROPERTY_NAMES  = 0
    PROPERTY_VALUES = 1
    PROPERTIES      = 2
    IPV4_TREE       = 3

    ALL_TYPES       = [
        PROPERTY_NAMES,
        PROPERTY_VALUES,
        PROPERTIES,
        IPV4_TREE
    ]

    @staticmethod
    def isValidId(id):
        return (id in BucketType.ALL_TYPES)
