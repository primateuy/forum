from odoo.tests.common import TransactionCase


class TestGenericSecurityRestrictionDebug(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestGenericSecurityRestrictionDebug, cls).setUpClass()
        cls.group_user = cls.env.ref('base.group_user')
        cls.demo_user = cls.env.ref('base.user_demo')

    def test_write_allow_debug_mode_user(self):

        self.assertFalse(self.demo_user.allowed_use_debug_mode)
        self.assertFalse(
            self.demo_user._gsr_is_debug_mode_allowed(self.demo_user.id))

        self.demo_user.write({
            'allowed_use_debug_mode': True
        })

        self.assertTrue(self.demo_user.allowed_use_debug_mode)
        self.assertTrue(
            self.demo_user._gsr_is_debug_mode_allowed(self.demo_user.id))

    def test_write_allow_debug_mode_groups_user(self):

        self.assertFalse(self.demo_user.allowed_use_debug_mode)
        self.assertFalse(self.group_user.allowed_use_debug_mode)

        self.assertFalse(
            self.demo_user._gsr_is_debug_mode_allowed(self.demo_user.id))

        self.group_user.write({
            'allowed_use_debug_mode': True
        })

        self.assertFalse(self.demo_user.allowed_use_debug_mode)
        self.assertTrue(self.group_user.allowed_use_debug_mode)
        self.assertTrue(
            self.demo_user._gsr_is_debug_mode_allowed(self.demo_user.id))
