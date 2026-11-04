package com.dsgpt.mobile

import org.junit.Assert.*
import org.junit.Test

class DevicesTest {
    @Test fun displayedPermissionsDoNotTurnModelGrantsIntoOwnerAccess() {
        val models = devicePermissions(listOf("models")).toMap()
        assertTrue(models.getValue("Model management"))
        assertFalse(models.getValue("Device administration"))
        assertFalse(models.getValue("Chat and personal memory"))
        val oldOwner = devicePermissions(listOf("admin")).toMap()
        assertTrue(oldOwner.getValue("Model management"))
        assertTrue(oldOwner.getValue("Device administration"))
        assertFalse(oldOwner.getValue("Work and project memory"))
        assertTrue(devicePermissions(emptyList()).none { it.second })
    }
}
