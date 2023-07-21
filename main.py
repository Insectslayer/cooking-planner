import csv
import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Dict, List, Tuple

import yaml
from requests import get, patch, post

ingredient_name = str
amount = float
unit = str
recipe_name = str

BASE_URL = 'https://api.notion.com'


def read_yml_config(filename: str | Path) -> Dict:
    if not Path(filename).exists():
        return {}

    with open(filename, 'r') as f:
        config = yaml.load(f, yaml.Loader)
        return config


def fetch_results_from_db(db_id: str, api_token: str, version: str, query_filter: Dict = None) -> List:
    headers = {'Notion-Version': version,
               'Authorization': f'Bearer {api_token}'}
    results = []
    # Pagination
    query_payload = {}
    if query_filter is not None:
        query_payload['filter'] = query_filter
    while True:
        r = post(f'{BASE_URL}/v1/databases/{db_id}/query',
                 headers=headers,
                 json=query_payload)
        output = json.loads(r.text)
        results.extend(output['results'])
        if output['has_more']:
            query_payload['start_cursor'] = output['next_cursor']
        else:
            break
    return results


def get_price_of_recipe(recipe_page_id: str, api_token: str, version: str) -> int:
    headers = {'Notion-Version': version,
               'Authorization': f'Bearer {api_token}'}
    r = get(f'{BASE_URL}/v1/blocks/{recipe_page_id}/children', headers=headers)
    recipe_page = json.loads(r.text)
    ingredients_db_id = recipe_page['results'][0]['id']

    results = fetch_results_from_db(ingredients_db_id, api_token, version)

    price_sum = 0
    for result in results:
        price_sum += result['properties']['Cena']['formula']['number']

    return price_sum


def update_prices(recipes_db_id: str, api_token: str, version: str) -> None:
    headers = {'Notion-Version': version,
               'Authorization': f'Bearer {api_token}'}

    results = fetch_results_from_db(recipes_db_id, api_token, version)

    for result in results:
        page_id = result['id']
        price = get_price_of_recipe(page_id, api_token, version)
        payload_data = {'properties': {'Cena': {'number': price}}}
        r = patch(f'{BASE_URL}/v1/pages/{page_id}',
                  headers=headers, json=payload_data)


def get_ingredients_of_recipe(recipe_page_id: str,
                              api_token: str,
                              version: str,
                              recipe_name: recipe_name) -> Dict[ingredient_name, List[Tuple[amount, unit, recipe_name]]]:
    '''
    returns: {'Ovoce':[(2.5, 'kg', 'Svačina')], ...}
    '''
    headers = {'Notion-Version': version,
               'Authorization': f'Bearer {api_token}'}
    r = get(f'{BASE_URL}/v1/blocks/{recipe_page_id}/children', headers=headers)
    recipe_page = json.loads(r.text)
    ingredients_db_id = recipe_page['results'][0]['id']

    results = fetch_results_from_db(ingredients_db_id, api_token, version)

    shopping_list = {}
    for result in results:
        try:
            i_name = result['properties']['Master Name']['rollup']['array'][0]['title'][0]['plain_text']
            i_amount = result['properties']['Počet']['number']
            i_unit = result['properties']['Jednotka']['rollup']['array'][0]['select']['name']
        except IndexError:
            print(f'Chyba v receptu {recipe_name}. Zkontrolujte, že každý řádek má přiřazenou ingredienci na pozici `Master Record`.')
        if i_name not in shopping_list:
            shopping_list[i_name] = [(i_amount, i_unit, recipe_name)]
        else:
            shopping_list[i_name].append((i_amount, i_unit, recipe_name))

    return shopping_list


def add_recipe_to_list(shopping_list: Dict[ingredient_name, List[Tuple[amount, unit, recipe_name]]],
                       recipe_list: Dict[ingredient_name, List[Tuple[amount, unit, recipe_name]]]) -> None:
    for item in recipe_list:
        if item not in shopping_list:
            shopping_list[item] = recipe_list[item]
        else:
            shopping_list[item].extend(recipe_list[item])


def get_master_ingredients(master_ingredients_db_id: str, api_token: str, version: str) -> Dict[str, List[ingredient_name]]:
    '''
    returns {'Trvanlivé': ['Fazole',...],...}
    '''
    results = fetch_results_from_db(
        master_ingredients_db_id, api_token, version)

    ingredient_types = {}
    for result in results:
        ingredient_name = result['properties']['Jméno']['title'][0]['plain_text']
        type_name = 'Nezařazeno'
        if result['properties']['Typ']['select'] is not None:
            type_name = result['properties']['Typ']['select']['name']
        if type_name not in ingredient_types:
            ingredient_types[type_name] = [ingredient_name]
        else:
            ingredient_types[type_name].append(ingredient_name)

    return ingredient_types


def write_ingredient_type_to_csv(writer,
                                 shopping_list: Dict[ingredient_name, List[Tuple[amount, unit, recipe_name]]],
                                 ingredient_type: str,
                                 ingredients: List[ingredient_name]):
    writer.writerow([ingredient_type])
    for ingredient in ingredients:
        if ingredient in shopping_list:
            for i, item in enumerate(shopping_list[ingredient]):
                if i == 0:
                    line = [ingredient]
                else:
                    line = ['']
                line.extend(item)
                writer.writerow(line)


def save_list_to_csv(filename: str,
                     shopping_list: Dict[ingredient_name, List[Tuple[amount, unit, recipe_name]]],
                     master_ingredients_db_id: str,
                     api_token: str,
                     version: str) -> None:
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        f.write('\ufeff')
        writer = csv.writer(f, delimiter=',')
        ingredient_types = get_master_ingredients(
            master_ingredients_db_id, api_token, version)
        for i_type in ingredient_types:
            write_ingredient_type_to_csv(
                writer, shopping_list, i_type, ingredient_types[i_type])


def create_shopping_list(recipes_db_id: str,
                         master_ingredients_db_id: str,
                         api_token: str,
                         version: str,
                         start: str,
                         end: str) -> None:
    date_filter = {
        "property": "Datum",
        "date": {
            "on_or_after": start,
            "on_or_before": end
        }
    }
    results = fetch_results_from_db(
        recipes_db_id, api_token, version, date_filter)

    shopping_list = {}
    for result in results:
        page_id = result['id']
        recipe_name = result['properties']['Jméno']['title'][0]['plain_text']
        recipe_list = get_ingredients_of_recipe(
            page_id, api_token, version, recipe_name)
        add_recipe_to_list(shopping_list, recipe_list)

    save_list_to_csv('_'.join(['nakup', start, end]) + '.csv',
                     shopping_list,
                     master_ingredients_db_id,
                     api_token,
                     version)


if __name__ == '__main__':
    parser = ArgumentParser(
        prog='Notion Integrace',
        description='''
            Tento skript aktualizuje tabulku vaření v místech,
            která Notion sám neumí. Přiřadí každému receptu aktuální cenu
            v závislosti na ingrediencích v receptu.
            
            Zároveň slouží k exportu nákupního seznamu do csv.''')
    parser.add_argument('-p',
                        '--price',
                        action='store_true',
                        help='Přepočítá aktuální cenu receptu v závislosti na ingrediencích.')
    parser.add_argument('-l',
                        '--list',
                        nargs=2,
                        metavar='DATE',
                        help='Vytvoří nákupní seznam z ingrediencí v receptech. Rozsah datumů (začátek i konec včetně), ze kterých jsou recepty brány, je zapsán ve formátu YYYY-MM-DD.')
    args = parser.parse_args()

    config = read_yml_config('config.yml')
    api_token = config['api_token']
    notion_version = config['notion_version']
    recipes_db_id = config['recipes_db_id']
    master_ingredients_db_id = config['master_ingredients_db_id']

    if args.price:
        update_prices(recipes_db_id, api_token, notion_version)
    # update_prices(recipes_db_id, api_token, notion_version)

    if args.list is not None:
        start, end = args.list
        create_shopping_list(recipes_db_id, master_ingredients_db_id,
                             api_token, notion_version, start, end)
