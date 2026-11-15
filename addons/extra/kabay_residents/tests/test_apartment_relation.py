from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKabayApartmentRelation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.condo = cls.env["kabay.condominium"].create({
            "name": "Condominio Relaciones", "code": "REL-1", "company_id": cls.company.id,
        })
        cls.building = cls.env["kabay.building"].create({
            "name": "Torre Relaciones", "code": "REL-A", "condominium_id": cls.condo.id,
        })
        cls.apartment = cls.env["kabay.apartment"].create({
            "name": "A-101", "code": "A-101", "building_id": cls.building.id,
        })
        cls.apartment2 = cls.env["kabay.apartment"].create({
            "name": "A-102", "code": "A-102", "building_id": cls.building.id,
        })
        cls.owner = cls.env["res.partner"].create({"name": "Propietaria Prueba", "company_type": "person"})
        cls.tenant = cls.env["res.partner"].create({"name": "Inquilino Prueba", "company_type": "person"})
        cls.resident = cls.env["res.partner"].create({"name": "Residente Prueba", "company_type": "person"})

    def _relation(self, partner=None, apartment=None, role="owner", **extra):
        values = {
            "partner_id": (partner or self.owner).id,
            "apartment_id": (apartment or self.apartment).id,
            "role": role,
            "date_start": "2026-01-01",
        }
        values.update(extra)
        return self.env["kabay.apartment.relation"].create(values)

    def test_roles_people_per_unit_and_person_multiple_units(self):
        owner_relation = self._relation(role="owner")
        tenant_relation = self._relation(partner=self.tenant, role="tenant")
        resident_relation = self._relation(partner=self.resident, role="authorized_resident")
        same_person_second_unit = self._relation(apartment=self.apartment2, role="owner")
        owner_relation.action_confirm()
        tenant_relation.action_confirm()
        resident_relation.action_confirm()
        same_person_second_unit.action_confirm()
        self.assertEqual(len(self.apartment.relation_ids), 3)
        self.assertIn(self.apartment2, self.owner.apartment_relation_ids.mapped("apartment_id"))
        self.assertEqual(owner_relation.company_id, self.company)

    def test_owner_and_tenant_roles_can_overlap(self):
        owner = self._relation(role="owner", date_end="2026-12-31")
        tenant = self._relation(partner=self.owner, role="tenant", date_end="2026-12-31")
        owner.action_confirm()
        tenant.action_confirm()
        self.assertEqual(owner.state, "confirmed")
        self.assertEqual(tenant.state, "confirmed")

    def test_duplicate_same_role_period_is_rejected_but_adjacent_period_is_allowed(self):
        first = self._relation(role="tenant", date_end="2026-01-10")
        with self.assertRaises(ValidationError):
            self._relation(role="tenant", date_start="2026-01-10", date_end="2026-01-20")
        adjacent = self._relation(role="tenant", date_start="2026-01-11", date_end="2026-01-20")
        self.assertTrue(first.exists())
        self.assertTrue(adjacent.exists())

    def test_date_end_cannot_precede_date_start(self):
        with self.assertRaises(ValidationError):
            self._relation(role="tenant", date_start="2026-02-01", date_end="2026-01-31")

    def test_finalize_preserves_history_and_new_relation_is_separate(self):
        old = self._relation(role="tenant", date_start="2020-01-01")
        old.action_confirm()
        old.action_end()
        self.assertEqual(old.state, "ended")
        self.assertEqual(old.date_end, fields.Date.context_today(self))
        with self.assertRaises(UserError):
            old.write({"partner_id": self.tenant.id})
        tomorrow = fields.Date.context_today(self) + timedelta(days=1)
        new = self._relation(role="tenant", date_start=tomorrow)
        new.action_confirm()
        self.assertTrue(old.exists())
        self.assertEqual(old.partner_id, self.owner)
        self.assertEqual(new.partner_id, self.owner)
        self.assertNotEqual(old.id, new.id)

    def test_share_is_optional_but_configured_distribution_must_total_100(self):
        unconfigured = self._relation(role="owner")
        unconfigured.action_confirm()
        self.assertEqual(unconfigured.state, "confirmed")

        apartment = self.env["kabay.apartment"].create({
            "name": "A-103", "code": "A-103", "building_id": self.building.id,
        })
        first = self._relation(apartment=apartment, role="owner", ownership_share=60.0)
        second = self._relation(
            partner=self.tenant, apartment=apartment, role="owner", ownership_share=40.0
        )
        first.action_confirm()
        second.action_confirm()
        self.assertEqual(first.state, "confirmed")
        self.assertEqual(second.state, "confirmed")

        apartment_bad = self.env["kabay.apartment"].create({
            "name": "A-104", "code": "A-104", "building_id": self.building.id,
        })
        incomplete = self._relation(apartment=apartment_bad, role="owner", ownership_share=50.0)
        with self.assertRaises(ValidationError):
            incomplete.action_confirm()

    def test_share_range_is_validated(self):
        with self.assertRaises(ValidationError):
            self._relation(role="owner", ownership_share=100.01)
        with self.assertRaises(ValidationError):
            self._relation(partner=self.tenant, role="tenant", ownership_share=40.0)

    def test_partner_and_apartment_company_must_be_compatible(self):
        other_company = self.env["res.company"].create({"name": "Kabay compañía del contacto"})
        partner = self.env["res.partner"].create({
            "name": "Contacto de otra compañía", "company_id": other_company.id,
        })
        with self.assertRaises(ValidationError):
            self._relation(partner=partner, role="tenant")

    def test_relationship_is_visible_in_both_directions_and_views_exist(self):
        relation = self._relation(role="authorized_resident")
        self.assertIn(relation, self.apartment.relation_ids)
        self.assertIn(relation, self.owner.apartment_relation_ids)
        self.assertEqual(relation.condominium_id, self.condo)
        self.assertEqual(relation.building_id, self.building)
        self.assertTrue(self.env.ref("kabay_residents.view_kabay_apartment_form_residents"))
        self.assertTrue(self.env.ref("kabay_residents.view_res_partner_form_kabay_relations"))

    def test_reception_can_read_but_cannot_change_relations(self):
        relation = self._relation(role="tenant")
        group_user = self.env.ref("base.group_user")
        reception_group = self.env.ref("kabay_base.group_kabay_reception")
        user = self.env["res.users"].create({
            "name": "Recepción Prueba", "login": "kabay-reception-test",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "group_ids": [(6, 0, [group_user.id, reception_group.id])],
        })
        relation_as_reception = relation.with_user(user)
        self.assertEqual(relation_as_reception.partner_id, self.owner)
        with self.assertRaises(AccessError):
            relation_as_reception.write({"notes": "No autorizado"})

    def test_relation_record_rule_restricts_other_companies(self):
        other_company = self.env["res.company"].create({"name": "Kabay compañía externa"})
        condo = self.env["kabay.condominium"].create({
            "name": "Condominio externo", "code": "EXT-1", "company_id": other_company.id,
        })
        building = self.env["kabay.building"].create({
            "name": "Torre externa", "code": "EXT-A", "condominium_id": condo.id,
        })
        apartment = self.env["kabay.apartment"].create({
            "name": "EXT-A-1", "code": "EXT-A-1", "building_id": building.id,
        })
        relation = self._relation(apartment=apartment, role="tenant")
        user = self.env["res.users"].create({
            "name": "Finanzas Unidad", "login": "kabay-finance-relation-test",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("kabay_base.group_kabay_finance").id,
            ])],
        })
        self.assertFalse(
            self.env["kabay.apartment.relation"].with_user(user).search([("id", "=", relation.id)])
        )

    def test_invoice_model_is_not_modified_or_linked_to_resident_history(self):
        relation = self.env["kabay.apartment.relation"]
        self.assertNotIn("account_move_id", relation._fields)
        self.assertNotIn("invoice_ids", relation._fields)
