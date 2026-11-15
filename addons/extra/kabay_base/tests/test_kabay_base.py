from psycopg2 import IntegrityError
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKabayBase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.condo = cls.env["kabay.condominium"].create({
            "name": "Condominio Uno", "code": "C-1", "company_id": cls.env.company.id,
        })
        cls.building = cls.env["kabay.building"].create({
            "name": "Torre A", "code": "A", "condominium_id": cls.condo.id,
        })

    def test_apartment_hierarchy_and_unlimited_apartments(self):
        apartments = self.env["kabay.apartment"].create([
            {"name": f"Unidad {n}", "code": f"U-{n}", "building_id": self.building.id}
            for n in range(1, 26)
        ])
        self.assertEqual(len(apartments), 25)
        self.assertEqual(set(apartments.mapped("condominium_id").ids), {self.condo.id})
        self.assertTrue(all(company == self.env.company for company in apartments.mapped("company_id")))

    def test_photo_limit_is_enforced_by_model(self):
        apartment = self.env["kabay.apartment"].create({
            "name": "Unidad foto", "code": "F-1", "building_id": self.building.id,
        })
        image_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pZcAAAAASUVORK5CYII="
        self.env["kabay.apartment.photo"].create([
            {"name": f"Foto {n}", "apartment_id": apartment.id, "image": image_data}
            for n in range(10)
        ])
        with self.assertRaises(ValidationError):
            self.env["kabay.apartment.photo"].create({
                "name": "Foto 11", "apartment_id": apartment.id, "image": image_data,
            })

    def test_photo_limit_is_enforced_when_moving_photos(self):
        apartment = self.env["kabay.apartment"].create({
            "name": "Unidad destino", "code": "DEST", "building_id": self.building.id,
        })
        source = self.env["kabay.apartment"].create({
            "name": "Unidad origen", "code": "ORIG", "building_id": self.building.id,
        })
        image_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pZcAAAAASUVORK5CYII="
        photos = self.env["kabay.apartment.photo"].create([
            {"name": f"Foto {n}", "apartment_id": apartment.id, "image": image_data}
            for n in range(10)
        ])
        movable = self.env["kabay.apartment.photo"].create({
            "name": "Foto móvil", "apartment_id": source.id, "image": image_data,
        })
        with self.assertRaises(ValidationError):
            movable.write({"apartment_id": apartment.id})
        self.assertEqual(len(photos), 10)
        self.assertEqual(movable.apartment_id, source)

    def test_company_is_inherited_through_the_hierarchy(self):
        other_company = self.env["res.company"].create({"name": "Kabay Otra compañía"})
        other_condo = self.env["kabay.condominium"].create({
            "name": "Otro condominio", "code": "C-OTHER", "company_id": other_company.id,
        })
        other_building = self.env["kabay.building"].create({
            "name": "Torre B", "code": "B", "condominium_id": other_condo.id,
        })
        apartment = self.env["kabay.apartment"].create({
            "name": "B-101", "code": "B-101", "building_id": other_building.id,
        })
        self.assertEqual(other_building.company_id, other_company)
        self.assertEqual(apartment.company_id, other_company)
        self.assertEqual(apartment.condominium_id, other_condo)

    def test_archiving_keeps_the_record_and_related_photo(self):
        apartment = self.env["kabay.apartment"].create({
            "name": "Unidad histórica", "code": "H-1", "building_id": self.building.id,
        })
        photo = self.env["kabay.apartment.photo"].create({
            "name": "Foto histórica", "apartment_id": apartment.id,
            "image": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pZcAAAAASUVORK5CYII=",
        })
        apartment.active = False
        self.assertTrue(apartment.exists())
        self.assertTrue(photo.exists())
        self.assertFalse(apartment.active)

    def test_group_permissions_and_company_rules(self):
        group_user = self.env.ref("base.group_user")
        finance_group = self.env.ref("kabay_base.group_kabay_finance")
        finance = self.env["res.users"].create({
            "name": "Finanzas Kabay", "login": "kabay-finance-test",
            "company_id": self.env.company.id,
            "company_ids": [(6, 0, [self.env.company.id])],
            "group_ids": [(6, 0, [group_user.id, finance_group.id])],
        })
        other_company = self.env["res.company"].create({"name": "Kabay Visible a otros"})
        hidden_condo = self.env["kabay.condominium"].create({
            "name": "Condominio restringido", "code": "RESTRICTED", "company_id": other_company.id,
        })
        visible = self.env["kabay.condominium"].with_user(finance).search([("id", "=", self.condo.id)])
        hidden = self.env["kabay.condominium"].with_user(finance).search([("id", "=", hidden_condo.id)])
        self.assertTrue(visible)
        self.assertFalse(hidden)
        with self.assertRaises(AccessError):
            self.env["kabay.condominium"].with_user(finance).create({
                "name": "No puede crear", "code": "NO-CREATE",
            })
        self.assertIn(
            self.env.ref("kabay_base.group_kabay_manager"),
            self.env.ref("base.group_system").implied_ids,
        )

    def test_kabay_administrator_can_manage_but_cannot_delete_structure(self):
        group_user = self.env.ref("base.group_user")
        manager_group = self.env.ref("kabay_base.group_kabay_manager")
        administrator = self.env["res.users"].create({
            "name": "Administrador Kabay", "login": "kabay-manager-test",
            "company_id": self.env.company.id,
            "company_ids": [(6, 0, [self.env.company.id])],
            "group_ids": [(6, 0, [group_user.id, manager_group.id])],
        })
        condominium = self.env["kabay.condominium"].with_user(administrator).create({
            "name": "Condominio de Administrador", "code": "ADMIN-TEST",
            "company_id": self.env.company.id,
        })
        self.assertTrue(condominium.exists())
        with self.assertRaises(AccessError):
            condominium.with_user(administrator).unlink()

    def test_apartment_codes_are_unique_per_building(self):
        self.env["kabay.apartment"].create({
            "name": "Unidad original", "code": "U-1", "building_id": self.building.id,
        })
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["kabay.apartment"].create({
                    "name": "Duplicada", "code": "U-1", "building_id": self.building.id,
                })
                self.env.flush_all()

    def test_codes_are_unique_only_in_their_parent_scope(self):
        second_condo = self.env["kabay.condominium"].create({
            "name": "Condominio Dos", "code": "C-2", "company_id": self.env.company.id,
        })
        second_building = self.env["kabay.building"].create({
            "name": "Otra Torre A", "code": "A", "condominium_id": second_condo.id,
        })
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["kabay.building"].create({
                    "name": "Torre A repetida", "code": "A", "condominium_id": self.condo.id,
                })
                self.env.flush_all()
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["kabay.condominium"].create({"name": "Código repetido", "code": "C-1"})
                self.env.flush_all()
        self.env["kabay.apartment"].create({
            "name": "Unidad original", "code": "U-1", "building_id": self.building.id,
        })
        same_apartment_code = self.env["kabay.apartment"].create({
            "name": "Unidad con código local repetido", "code": "U-1",
            "building_id": second_building.id,
        })
        self.assertEqual(same_apartment_code.building_id, second_building)
